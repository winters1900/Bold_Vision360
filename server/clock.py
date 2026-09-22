"""Infer SDK timestamp units from observed progression; preserve raw values."""
class CameraClock:
    def __init__(self):
        self.first={};self.previous={};self.units={};self.offset=None;self.diagnostics={}

    def align(self,kind,raw,receipt):
        previous=self.previous.get(kind)
        if previous is not None and raw<previous:
            self.first.clear();self.previous.clear();self.units.clear();self.offset=None;self.diagnostics.clear()
        self.previous[kind]=raw
        if kind not in self.first:self.first[kind]=(raw,receipt)
        baseline,host=self.first[kind]
        elapsed=receipt-host
        if elapsed>=.5 and raw>baseline:
            rate=(raw-baseline)/elapsed
            options=((1e-6,'microseconds',1e6),(1e-3,'milliseconds',1e3))
            matched=next(((scale,name,expected) for scale,name,expected in options if .7<rate/expected<1.3),None)
            if matched:
                scale,name,expected=matched;self.units[kind]=scale
                self.diagnostics[kind]={'unit':name,'rate_ratio':round(rate/expected,3),'verified':True}
            else:self.diagnostics[kind]={'unit':'unknown','ticks_per_second':round(rate,3),'verified':False}
            self.first[kind]=(raw,receipt)
        if kind not in self.units:return receipt
        native=raw*self.units[kind]
        candidate=receipt-native
        self.offset=candidate if self.offset is None else min(self.offset,candidate)
        return min(receipt,native+self.offset)
