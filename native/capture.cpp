#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <camera/camera.h>
#include <camera/device_discovery.h>
#include <ins_realtime_stitcher.h>
#include <ins_stitcher.h>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <deque>
#include <iostream>
#include <mutex>
#include <sstream>
#include <thread>
#include <vector>

using Clock = std::chrono::steady_clock;
struct Packet { std::string meta; std::vector<uint8_t> data; };
struct Buffer {
    std::mutex mutex;
    std::condition_variable cv;
    Packet video;
    std::deque<Packet> audio;
    std::atomic<uint64_t> frames{0}, audioPackets{0}, overflows{0};
    std::atomic<bool> running{true};
    std::atomic<int> pixelFormat{-1};
    std::atomic<int> stride{0};
};
static double qpcSeconds() {
    LARGE_INTEGER counter, frequency;
    QueryPerformanceCounter(&counter); QueryPerformanceFrequency(&frequency);
    return double(counter.QuadPart) / double(frequency.QuadPart);
}
static std::string stamp(const char* kind, int64_t timestamp) {
    std::ostringstream s;
    s.precision(17);
    s << "\"kind\":\"" << kind << "\",\"camera_us\":" << timestamp
      << ",\"host_time\":" << qpcSeconds();
    return s.str();
}
static bool sendAll(SOCKET sock, const void* ptr, size_t length) {
    auto data = static_cast<const char*>(ptr);
    while (length) { int sent = send(sock, data, int(length), 0); if (sent <= 0) return false;
        data += sent; length -= sent; }
    return true;
}
static bool sendPacket(SOCKET sock, const Packet& p) {
    auto header = "{" + p.meta + ",\"payload_bytes\":" + std::to_string(p.data.size()) + "}";
    uint32_t size = htonl(uint32_t(header.size()));
    return sendAll(sock, &size, 4) && sendAll(sock, header.data(), header.size()) &&
        sendAll(sock, p.data.data(), p.data.size());
}
class Delegate : public ins_camera::StreamDelegate {
    std::shared_ptr<ins::RealTimeStitcher> stitcher;
    Buffer& b;
public:
    Delegate(std::shared_ptr<ins::RealTimeStitcher> s, Buffer& buffer):stitcher(s),b(buffer){}
    void OnVideoData(const uint8_t* data, size_t size, int64_t ts, uint8_t type, int index) override {
        if (b.running) stitcher->HandleVideoData(data, size, ts, type, index);
    }
    void OnAudioData(const uint8_t* data, size_t size, int64_t ts) override {
        if (!b.running || size > 1024 * 1024) return;
        Packet p{stamp("aac", ts), std::vector<uint8_t>(data, data + size)};
        std::lock_guard<std::mutex> lock(b.mutex);
        if (b.audio.size() >= 128) { b.audio.clear(); ++b.overflows; p.meta += ",\"discontinuity\":true"; }
        b.audio.push_back(std::move(p)); ++b.audioPackets; b.cv.notify_one();
    }
    void OnGyroData(const std::vector<ins_camera::GyroData>& data) override {
        std::vector<ins::GyroData> out; out.reserve(data.size());
        for (const auto& g : data) { ins::GyroData v{}; v.timestamp=g.timestamp;
            v.ax=g.ax;v.ay=g.ay;v.az=g.az;v.gx=g.gx;v.gy=g.gy;v.gz=g.gz;out.push_back(v); }
        if(b.running) stitcher->HandleGyroData(out);
    }
    void OnExposureData(const ins_camera::ExposureData& data) override {
        ins::ExposureData out{};out.timestamp=data.timestamp;out.exposure_time=data.exposure_time;
        if(b.running) stitcher->HandleExposureData(out);
    }
};
int main(int argc,char** argv) {
    if(argc<3){std::cerr<<"usage: bold_capture PORT MODEL_DIR [software]\n";return 2;}
    WSADATA wsa; WSAStartup(MAKEWORD(2,2), &wsa);
    SOCKET sock = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    sockaddr_in addr{};addr.sin_family=AF_INET;addr.sin_port=htons(static_cast<u_short>(std::stoi(argv[1])));
    inet_pton(AF_INET,"127.0.0.1", &addr.sin_addr);
    if(connect(sock,reinterpret_cast<sockaddr*>(&addr),sizeof(addr))){std::cerr<<"service unavailable\n";return 3;}
    DWORD timeout=2000; setsockopt(sock,SOL_SOCKET,SO_SNDTIMEO,reinterpret_cast<char*>(&timeout),sizeof(timeout));
    Buffer buffer;
    std::thread control([&] {
        HANDLE input=GetStdHandle(STD_INPUT_HANDLE);std::string command;
        while(buffer.running){
            DWORD available=0;
            if(!PeekNamedPipe(input,nullptr,0,nullptr,&available,nullptr)){buffer.running=false;break;}
            if(available){
                char chunk[64];DWORD count=0;
                if(!ReadFile(input,chunk,std::min<DWORD>(available,64),&count,nullptr)){buffer.running=false;break;}
                command.append(chunk,count);
                if(command.find("stop\n")!=std::string::npos){buffer.running=false;break;}
                if(command.size()>1024)command.clear();
            }else Sleep(50);
        }
        buffer.cv.notify_all();
    });
    int result=0;
    try {
        ins::InitEnv(); ins::SetModelFileRootDir(argv[2]);
        ins_camera::SetLogLevel(ins_camera::LogLevel::WARNING);
        ins::SetLogLevel(ins::InsLogLevel::WARNING);
        ins_camera::DeviceDiscovery discovery;
        auto list=discovery.GetAvailableDevices();
        if(list.empty()) throw std::runtime_error("No camera: check USB Android mode and other camera applications");
        auto serial=list[0].serial_number;
        auto cam=std::make_shared<ins_camera::Camera>(list[0].info);
        bool opened=cam->Open();discovery.FreeDeviceDescriptors(list);
        if(!opened) throw std::runtime_error("Camera open failed");
        auto stitcher=std::make_shared<ins::RealTimeStitcher>();
        auto preview=cam->GetPreviewParam();
        ins::CameraInfo info;info.cameraName=preview.camera_name;info.decode_type=static_cast<ins::VideoDecodeType>(preview.encode_type);
        std::vector<std::string> calib;for(size_t i=0;i<preview.GetCalibrationCount();++i)calib.push_back(preview.GetCalibration(i));
        info.SetCalibration(calib,preview.GetCropSrcWidth(),preview.GetCropSrcHeight(),preview.GetCropDstWidth(),preview.GetCropDstHeight(),preview.GetCropOffsetX(),preview.GetCropOffsetY());
        stitcher->SetCameraInfo(info);stitcher->SetStitchType(ins::STITCH_TYPE::DYNAMICSTITCH);
        stitcher->EnableFlowState(true);stitcher->EnableDirectionLock(false);stitcher->SetOutputSize(960,480);
        if(argc>3)stitcher->SetSoftwareCodecUsage(false,true);
        stitcher->SetStitchRealTimeDataCallback([&](uint8_t* data[4],int strides[4],int w,int h,int fmt,int64_t ts){
            buffer.pixelFormat=fmt;
            buffer.stride=strides[0];
            static bool described=false;
            if(!described){std::cerr<<"OUTPUT_LAYOUT fmt="<<fmt<<" size="<<w<<"x"<<h<<" strides="<<strides[0]<<","<<strides[1]<<","<<strides[2]<<" planes="<<(data[1]!=nullptr)<<","<<(data[2]!=nullptr)<<std::endl;described=true;}
            // MediaSDK 3.1.7 on this X4 Air labels packed RGBA as 0, despite its header
            // documenting AVPixelFormat. Accept that quirk only for a packed 4-byte row
            // with opaque alpha samples; never interpret actual planar YUV420P as RGBA.
            bool packedQuirk=fmt==0 && w>0 && w<=4096 && h>0 && h<=2048 && strides[0]==w*4 && !data[1] && !data[2];
            if(packedQuirk && data[0] && w>0 && h>0){
                for(int x=0;x<w;x+=std::max(1,w/16))if(data[0][x*4+3]!=255){packedQuirk=false;break;}
            }
            if(!buffer.running || (fmt!=26 && !packedQuirk) || !data[0] || w<=0 || h<=0 || w>4096 || h>2048 || strides[0]<w*4) return;
            Packet p{stamp("rgba",ts)+",\"width\":"+std::to_string(w)+",\"height\":"+std::to_string(h),{}};
            p.data.resize(size_t(w)*h*4);
            for(int y=0;y<h;++y)memcpy(p.data.data()+size_t(y)*w*4,data[0]+size_t(y)*strides[0],size_t(w)*4);
            std::lock_guard<std::mutex> lock(buffer.mutex);buffer.video=std::move(p);++buffer.frames;buffer.cv.notify_one();
        });
        std::shared_ptr<ins_camera::StreamDelegate> delegate=std::make_shared<Delegate>(stitcher,buffer);
        cam->SetStreamDelegate(delegate);
        bool audioMode=cam->SetVideoSubMode(ins_camera::SubVideoMode::VIDEO_LIVEVIEW);
        ins_camera::LiveStreamParam param;
        param.video_resolution=ins_camera::VideoResolution::RES_1440_720P30;
        param.lrv_video_resulution=ins_camera::VideoResolution::RES_1440_720P30;
        param.video_bitrate=1024*1024/2;param.using_lrv=false;param.enable_audio=audioMode;param.is_for_live=audioMode;
        bool streaming=cam->StartLiveStreaming(param);
        if(!streaming && audioMode) {cam->SetVideoSubMode(ins_camera::SubVideoMode::VIDEO_NORMAL);audioMode=false;
            param.enable_audio=false;param.is_for_live=false;streaming=cam->StartLiveStreaming(param);}
        if(streaming) {
            stitcher->StartStitch();
            auto lastStatus=Clock::now()-std::chrono::seconds(2);
            while(buffer.running){
                std::deque<Packet> packets;
                {std::unique_lock<std::mutex> lock(buffer.mutex);buffer.cv.wait_for(lock,std::chrono::milliseconds(100));
                    packets.swap(buffer.audio);if(!buffer.video.data.empty()){packets.push_back(std::move(buffer.video));buffer.video=Packet{};}}
                for(const auto& p:packets)if(!sendPacket(sock,p)){buffer.running=false;break;}
                if(Clock::now()-lastStatus>std::chrono::seconds(1)){
                    std::ostringstream s;s<<"\"kind\":\"status\",\"serial\":\""<<serial<<"\",\"audio_mode\":"<<(audioMode?"true":"false")
                        <<",\"frames\":"<<buffer.frames<<",\"audio_packets\":"<<buffer.audioPackets<<",\"overflows\":"<<buffer.overflows
                        <<",\"pixel_format\":"<<buffer.pixelFormat<<",\"row_stride\":"<<buffer.stride;
                    if(!sendPacket(sock,{s.str(),{}}))buffer.running=false;lastStatus=Clock::now();
                }
            }
        } else result=4;
        buffer.running=false;
        if(streaming)cam->StopLiveStreaming();
        stitcher->CancelStitch();
        if(audioMode)cam->SetVideoSubMode(ins_camera::SubVideoMode::VIDEO_NORMAL);
        cam->Close();
    }catch(const std::exception& e){std::cerr<<e.what()<<std::endl;result=5;}
    buffer.running=false;buffer.cv.notify_all();control.join();
    closesocket(sock);WSACleanup();return result;
}
