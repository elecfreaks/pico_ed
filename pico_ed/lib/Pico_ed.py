import time
import utime
from machine import I2C, Pin, PWM


_MODE_REGISTER = const(0x00)
_FRAME_REGISTER = const(0x01)
_AUTOPLAY1_REGISTER = const(0x02)
_AUTOPLAY2_REGISTER = const(0x03)
_BLINK_REGISTER = const(0x05)
_AUDIOSYNC_REGISTER = const(0x06)
_BREATH1_REGISTER = const(0x08)
_BREATH2_REGISTER = const(0x09)
_SHUTDOWN_REGISTER = const(0x0a)
_GAIN_REGISTER = const(0x0b)
_ADC_REGISTER = const(0x0c)

_CONFIG_BANK = const(0x0b)
_BANK_ADDRESS = const(0xfd)

_PICTURE_MODE = const(0x00)
_AUTOPLAY_MODE = const(0x08)
_AUDIOPLAY_MODE = const(0x18) 

_ENABLE_OFFSET = const(0x00)
_BLINK_OFFSET = const(0x12)
_COLOR_OFFSET = const(0x24)

class Matrix:
    width = 17
    height = 7

    def __init__(self, i2c, address=0x74):
        self.i2c = i2c
        self.address = address
        self.reset()
        self.init()

    def _bank(self, bank=None):
        if bank is None:
            return self.i2c.readfrom_mem(self.address, _BANK_ADDRESS, 1)[0]
        self.i2c.writeto_mem(self.address, _BANK_ADDRESS, bytearray([bank]))

    def _register(self, bank, register, value=None):
        self._bank(bank)
        if value is None:
            return self.i2c.readfrom_mem(self.address, register, 1)[0]
        self.i2c.writeto_mem(self.address, register, bytearray([value]))

    def _mode(self, mode=None):
        return self._register(_CONFIG_BANK, _MODE_REGISTER, mode)

    def init(self):
        self._mode(_PICTURE_MODE)
        self.frame(0)
        for frame in range(8):
            self.fill(0, False, frame=frame)
            for col in range(18):
                self._register(frame, _ENABLE_OFFSET + col, 0xff)
        self.audio_sync(False)

    def reset(self):
        self.sleep(True)
        utime.sleep_us(10)
        self.sleep(False)

    def sleep(self, value):
        return self._register(_CONFIG_BANK, _SHUTDOWN_REGISTER, not value)

    def autoplay(self, delay=0, loops=0, frames=0):
        if delay == 0:
            self._mode(_PICTURE_MODE)
            return
        delay //= 11
        if not 0 <= loops <= 7:
            raise ValueError("Loops out of range")
        if not 0 <= frames <= 7:
            raise ValueError("Frames out of range")
        if not 1 <= delay <= 64:
            raise ValueError("Delay out of range")
        self._register(_CONFIG_BANK, _AUTOPLAY1_REGISTER, loops << 4 | frames)
        self._register(_CONFIG_BANK, _AUTOPLAY2_REGISTER, delay % 64)
        self._mode(_AUTOPLAY_MODE | self._frame)

    def fade(self, fade_in=None, fade_out=None, pause=0):
        if fade_in is None and fade_out is None:
            self._register(_CONFIG_BANK, _BREATH2_REGISTER, 0)
        elif fade_in is None:
            fade_in = fade_out
        elif fade_out is None:
            fade_out = fade_in
        fade_in = int(math.log(fade_in / 26, 2))
        fade_out = int(math.log(fade_out / 26, 2))
        pause = int(math.log(pause / 26, 2))
        if not 0 <= fade_in <= 7:
            raise ValueError("Fade in out of range")
        if not 0 <= fade_out <= 7:
            raise ValueError("Fade out out of range")
        if not 0 <= pause <= 7:
            raise ValueError("Pause out of range")
        self._register(_CONFIG_BANK, _BREATH1_REGISTER, fade_out << 4 | fade_in)
        self._register(_CONFIG_BANK, _BREATH2_REGISTER, 1 << 4 | pause)

    def frame(self, frame=None, show=True):
        if frame is None:
            return self._frame
        if not 0 <= frame <= 8:
            raise ValueError("Frame out of range")
        self._frame = frame
        if show:
            self._register(_CONFIG_BANK, _FRAME_REGISTER, frame);

    def audio_sync(self, value=None):
        return self._register(_CONFIG_BANK, _AUDIOSYNC_REGISTER, value)

    def audio_play(self, sample_rate, audio_gain=0,
                   agc_enable=False, agc_fast=False):
        if sample_rate == 0:
            self._mode(_PICTURE_MODE)
            return
        sample_rate //= 46
        if not 1 <= sample_rate <= 256:
            raise ValueError("Sample rate out of range")
        self._register(_CONFIG_BANK, _ADC_REGISTER, sample_rate % 256)
        audio_gain //= 3
        if not 0 <= audio_gain <= 7:
            raise ValueError("Audio gain out of range")
        self._register(_CONFIG_BANK, _GAIN_REGISTER,
                       bool(agc_enable) << 3 | bool(agc_fast) << 4 | audio_gain)
        self._mode(_AUDIOPLAY_MODE)

    def blink(self, rate=None):
        if rate is None:
            return (self._register(_CONFIG_BANK, _BLINK_REGISTER) & 0x07) * 270
        elif rate == 0:
            self._register(_CONFIG_BANK, _BLINK_REGISTER, 0x00)
            return
        rate //= 270
        self._register(_CONFIG_BANK, _BLINK_REGISTER, rate & 0x07 | 0x08)

    def fill(self, color=None, blink=None, frame=None):
        if frame is None:
            frame = self._frame
        self._bank(frame)
        if color is not None:
            if not 0 <= color <= 255:
                raise ValueError("Color out of range")
            data = bytearray([color] * 24)
            for row in range(6):
                self.i2c.writeto_mem(self.address,
                                     _COLOR_OFFSET + row * 24, data)
        if blink is not None:
            data = bool(blink) * 0xff
            for col in range(18):
                self._register(frame, _BLINK_OFFSET + col, data)

    def write_frame(self, data, frame=None):
        if len(data) > 144:
            raise ValueError("Bytearray too large for frame")
        if frame is None:
            frame = self._frame
        self._bank(frame)
        self.i2c.writeto_mem(self.address, _COLOR_OFFSET, data)

    def _pixel_addr(self, x, y):
        if x > 8:
            x = 17 - x
            y += 8
        else:
            y = 7 - y
            
            
        return x * 16 + y

    def pixel(self, x, y, color=None, blink=None, frame=None):
        if not 0 <= x <= self.width:
            return
        if not 0 <= y <= self.height:
            return
        pixel = self._pixel_addr(x, y)
        #if color is None and blink is None:
        #    return self._register(self._frame, pixel)
        if frame is None:
            frame = self._frame
        if color is not None:
            if not 0 <= color <= 255:
                raise ValueError("Color out of range")
            self._register(frame, _COLOR_OFFSET + pixel, color)
        #if blink is not None:
        #    addr, bit = divmod(pixel, 8)
        #    bits = self._register(frame, _BLINK_OFFSET + addr)
        #    if blink:
        #        bits |= 1 << bit
        #    else:
        #        bits &= ~(1 << bit)
        #    self._register(frame, _BLINK_OFFSET + addr, bits)
     


class Display(Matrix):
    def __init__(self, i2c, address=0x74):
        super().__init__(i2c, address=0x74)
        
        self.wordStock = {
            "A":[[1,0], [2,0], [3,0], [0,1], [4,1], [0,2], [4,2], [0,3], [4,3], [0,4], [1,4], [2,4], [3,4], [4,4], [0,5], [4,5], [0,6], [4,6]],
            "B":[[0,0], [1,0], [2,0], [3,0], [0,1], [4,1], [0,2], [4,2], [0,3], [1,3], [2,3], [3,3], [0,4], [4,4], [0,5], [4,5], [0,6], [1,6], [2,6], [3,6]],
            "C":[[1,0], [2,0], [3,0], [0,1], [4,1], [0,2], [0,3], [0,4], [0,5], [4,5], [1,6], [2,6], [3,6]],
            "D":[[0,0], [1,0], [2,0], [0,1], [3,1], [0,2], [4,2], [0,3], [4,3], [0,4], [4,4], [0,5], [3,5], [0,6], [1,6], [2,6]],
            "E":[[0,0], [1,0], [2,0], [3,0], [4,0], [0,1], [0,2], [0,3], [1,3], [2,3], [3,3], [0,4], [0,5], [0,6], [1,6], [2,6], [3,6], [4,6]],
            "F":[[0,0], [1,0], [2,0], [3,0], [4,0], [0,1], [0,2], [0,3], [1,3], [2,3], [0,4], [0,5], [0,6]],
            "G":[[1,0], [2,0], [3,0], [0,1], [4,1], [0,2], [0,3], [0,4], [3,4], [4,4], [0,5], [4,5], [1,6], [2,6], [3,6]],
            "H":[[0,0], [4,0], [0,1], [4,1], [0,2], [4,2], [0,3], [1,3], [2,3], [3,3], [4,3], [0,4], [4,4], [0,5], [4,5], [0,6], [4,6]],
            "I":[[1,0], [2,0], [3,0], [2,1], [2,2], [2,3], [2,4], [2,5], [2,6], [1,6], [2,6], [3,6]],
            "J":[[2,0], [3,0], [4,0], [3,1], [3,2], [3,3], [3,4], [0,5], [3,5], [1,6], [2,6]],
            "K":[[0,0], [4,0], [0,1], [3,1], [0,2], [2,2], [0,3], [1,3], [0,4], [2,4], [0,5], [3,5], [0,6], [4,6]],
            "L":[[0,0], [0,1], [0,2], [0,3], [0,4], [0,5], [0,6], [1,6], [2,6], [3,6], [4,6]],
            "M":[[0,0], [4,0], [0,1], [1,1], [3,1], [4,1], [0,2], [2,2], [4,2], [0,3], [4,3], [0,4], [4,4], [0,5], [4,5], [0,6], [4,6]],
            "N":[[0,0], [4,0], [0,1], [4,1], [0,2], [1,2], [4,2], [0,3], [2,3], [4,3], [0,4], [3,4], [4,4], [0,5], [4,5], [0,6], [4,6]],
            "O":[[1,0], [2,0], [3,0], [0,1], [4,1], [0,2], [4,2], [0,3], [4,3], [0,4], [4,4], [0,5], [4,5], [1,6], [2,6], [3,6]],
            "P":[[0,0], [1,0], [2,0], [3,0], [0,1], [4,1], [0,2], [4,2], [0,3], [1,3], [2,3], [3,3], [0,4], [0,5], [0,6]],
            "Q":[[1,0], [2,0], [3,0], [0,1], [4,1], [0,2], [4,2], [0,3], [4,3], [0,4], [2,4], [4,4], [0,5], [3,5], [1,6], [2,6], [4,6]],
            "R":[[0,0], [1,0], [2,0], [3,0], [0,1], [4,1], [0,2], [4,2], [0,3], [1,3], [2,3], [3,3], [0,4], [2,4], [0,5], [3,5], [0,6], [4,6]],
            "S":[[1,0], [2,0], [3,0], [4,0], [0,1], [0,2], [1,3], [2,3], [3,3], [4,4], [4,5], [0,6], [1,6], [2,6], [3,6]],
            "T":[[0,0], [1,0], [2,0], [3,0], [4,0], [2,1], [2,2], [2,3], [2,4], [2,5], [2,6]],
            "U":[[0,0], [4,0], [0,1], [4,1], [0,2], [4,2], [0,3], [4,3], [0,4], [4,4], [0,5], [4,5], [1,6], [2,6], [3,6]],
            "V":[[0,0], [4,0], [0,1], [4,1], [0,2], [4,2], [0,3], [4,3], [0,4], [4,4], [1,5], [3,5], [2,6]],
            "W":[[0,0], [4,0], [0,1], [4,1], [0,2], [4,2], [0,3], [2,3], [4,3], [0,4], [2,4], [4,4], [0,5], [1,5], [3,5], [4,5], [0,6], [4,6]],
            "X":[[0,0], [4,0], [0,1], [4,1], [1,2], [3,2], [2,3], [1,4], [3,4], [0,5], [4,5], [0,6], [4,6]],
            "Y":[[0,0], [4,0], [0,1], [4,1], [1,2], [3,2], [2,3], [2,4], [2,5], [2,6]],
            "Z":[[0,0], [1,0], [2,0], [3,0], [4,0], [4,1], [3,2], [2,3], [1,4], [0,5], [0,6], [1,6], [2,6], [3,6], [4,6]],
            "a":[[1,2], [2,2], [3,2], [4,3], [1,4], [2,4], [3,4], [4,4], [0,5], [4,5], [1,6], [2,6], [3,6], [4,6]],
            "b":[[0,0], [0,1], [0,2], [2,2], [3,2], [0,3], [1,3], [4,3], [0,4], [4,4], [0,5], [4,5], [0,6], [1,6], [2,6], [3,6]],
            "c":[[1,2], [2,2], [3,2], [0,3], [0,4], [0,5], [4,5], [1,6], [2,6], [3,6]],
            "d":[[4,0], [4,1], [1,2], [2,2], [4,2], [0,3], [3,3], [4,3], [0,4], [4,4], [0,5], [4,5], [1,6], [2,6], [3,6], [4,6]],
            "e":[[1,2], [2,2], [3,2], [0,3], [4,3], [0,4], [1,4], [2,4], [3,4], [4,4], [0,5], [1,6], [2,6], [3,6]],    
            "f":[[2,0], [3,0], [1,1], [4,1], [1,2], [0,3], [1,3], [2,3], [1,4], [1,5], [1,6]],
            "g":[[1,2], [2,2], [3,2], [4,2], [0,3], [4,3], [1,4], [2,4], [3,4], [4,4], [4,5], [2,6], [3,6]],
            "h":[[0,0], [0,1], [0,2], [2,2], [3,2], [0,3], [1,3], [4,3], [0,4], [4,4], [0,5], [4,5], [0,6], [4,6]],
            "i":[[2,0], [1,2], [2,2], [2,3], [2,4], [2,5], [1,6], [2,6], [3,6]],
            "j":[[3,0], [2,2], [3,2], [3,3], [3,4], [0,5], [3,5], [1,6], [2,6]],
            "k":[[1,0], [1,1], [1,2], [4,2], [1,3], [3,3], [1,4], [2,4], [1,5], [3,5], [1,6], [4,6]],
            "l":[[1,0], [2,0], [2,1], [2,2], [2,3], [2,4], [2,5], [1,6], [2,6], [3,6]],
            "m":[[0,2], [1,2], [3,2], [0,3], [2,3], [4,3], [0,4], [2,4], [4,4], [0,5], [4,5], [0,6], [4,6]],
            "n":[[0,2], [2,2], [3,2], [0,3], [1,3], [4,3], [0,4], [4,4], [0,5], [4,5], [0,6], [4,6]],
            "o":[[1,2], [2,2], [3,2], [0,3], [4,3], [0,4], [4,4], [0,5], [4,5], [1,6], [2,6], [3,6]],
            "p":[[0,2], [1,2], [2,2], [3,2], [0,3], [4,3], [0,4], [1,4], [2,4], [3,4], [0,5], [0,6]],
            "q":[[1,2], [2,2], [4,2], [0,3], [3,3], [4,3], [1,4], [2,4], [3,4], [4,4], [4,5], [4,6]],
            "r":[[0,2], [2,2], [3,2], [0,3], [1,3], [4,3], [0,4], [0,5], [0,6]],
            "s":[[1,2], [2,2], [3,2], [0,3], [1,4], [2,4], [3,4], [4,5], [0,6], [1,6], [2,6], [3,6]],
            "t":[[1,0], [1,1], [0,2], [1,2], [2,2], [1,3], [1,4], [1,5], [4,5], [2,6], [3,6]],
            "u":[[0,2], [4,2], [0,3], [4,3], [0,4], [4,4], [0,5], [3,5], [4,5], [1,6], [2,6], [4,6]],
            "v":[[0,2], [4,2], [0,3], [4,3], [0,4], [4,4], [1,5], [3,5], [2,6]],
            "w":[[0,2], [4,2], [0,3], [4,3], [0,4], [2,4], [4,4], [0,5], [2,5], [4,5], [1,6], [3,6]],
            "x":[[0,2], [4,2], [1,3], [3,3], [2,4], [1,5], [3,5], [0,6], [4,6]],
            "y":[[0,2], [4,2], [0,3], [4,3], [1,4], [2,4], [3,4], [4,4], [4,5], [1,6], [2,6], [3,6]],
            "z":[[0,2], [1,2], [2,2], [3,2], [4,2], [3,3], [2,4], [1,5], [0,6], [1,6], [2,6], [3,6], [4,6]],
            " ":[],
            "0":[[1,0], [2,0], [3,0], [0,1], [4,1], [0,2], [3,2], [4,2], [0,3], [2,3], [4,3], [0,4], [1,4], [4,4], [0,5], [4,5], [1,6], [2,6], [3,6]],
            "1":[[2,0], [1,1], [2,1], [2,2], [2,3], [2,4], [2,5], [1,6], [2,6], [3,6]],
            "2":[[1,0], [2,0], [3,0], [0,1], [4,1], [4,2], [3,3], [2,4], [1,5], [0,6], [1,6], [2,6], [3,6], [4,6]],
            "3":[[0,0], [1,0], [2,0], [3,0], [4,0], [3,1], [2,2], [3,3], [4,4], [0,5], [4,5], [1,6], [2,6], [3,6]],
            "4":[[3,0], [2,1], [3,1], [1,2], [3,2], [0,3], [3,3], [0,4], [1,4], [2,4], [3,4], [4,4], [3,5], [3,6]],
            "5":[[0,0], [1,0], [2,0], [3,0], [4,0], [0,1], [0,2], [1,2], [2,2], [3,2], [4,3], [4,4], [0,5], [4,5], [1,6], [2,6], [3,6]],
            "6":[[2,0], [3,0], [1,1], [0,2], [0,3], [1,3], [2,3], [3,3], [0,4], [4,4], [0,5], [4,5], [1,6], [2,6], [3,6]],
            "7":[[0,0], [1,0], [2,0], [3,0], [4,0], [4,1], [3,2], [2,3], [1,4], [1,5], [1,6]],
            "8":[[1,0], [2,0], [3,0], [0,1], [4,1], [0,2], [4,2], [1,3], [2,3], [3,3], [0,4], [4,4], [0,5], [4,5], [1,6], [2,6], [3,6]],
            "9":[[1,0], [2,0], [3,0], [0,1], [4,1], [0,2], [4,2], [1,3], [2,3], [3,3], [4,3], [4,4], [3,5], [1,6], [2,6]]
                }
        
        
        
    def show(self, string_list):
        self.fill(0)
        strlist = str(string_list)
        if (len(strlist)<4):
            for strcount in range(len(strlist)):
                for a in range(len(self.wordStock[strlist[strcount]])):
                    self.pixel(self.wordStock[strlist[strcount]][a][0]+strcount*6, self.wordStock[strlist[strcount]][a][1], 10)   
        if (len(strlist) >3):
            for offset in range(0, -6*len(strlist), -1):
                for strcount in range(len(strlist)):
                    skewing = strcount*6+offset
                    for strNum in range(len(self.wordStock[strlist[strcount]])):
                        if self.wordStock[strlist[strcount]][strNum][0]+skewing >= 0:
                            self.pixel(self.wordStock[strlist[strcount]][strNum][0]+skewing, self.wordStock[strlist[strcount]][strNum][1], 20)
                        else:
                            pass
                time.sleep(0.05)    
                self.fill(0)
                
                


class Button():
    def __init__(self, keyname):
        if keyname == "A":
            self.keyname = 20
        if keyname == "B":
            self.keyname = 21
        
    def is_pressed(self):
        button = Pin(self.keyname, Pin.IN)
        if button.value() == 0:
            time.sleep(0.13)
            if button.value() == 0:
                return 1
            
            
            
class Led():
    def __init__(self):
        self.ledpin = 25
        self.led = Pin(self.ledpin, Pin.OUT)
        self.tones = {'1': 262, '2': 294, '3': 330, '4': 349, '5': 392, '6': 440, '7': 494, '-': 0}
        
    def on(self):
        self.led.value(1)
        
        
    def off(self):
        self.led.value(0)
        

class Music():
    def __init__(self):
        self.tones = {'1': 262, '2': 294, '3': 330, '4': 349, '5': 392, '6': 440, '7': 494, '-': 0}
        self.buzzer = PWM(Pin(0))
        
    def phonate(self,melody):
        for tone in melody:
            freq = self.tones[tone]
            if freq:
                self.buzzer.duty_u16(1000) # 调整PWM的频率，使其发出指定的音调
                self.buzzer.freq(freq)
            else:
                self.buzzer.duty_u16(0)  # 空拍时一样不上电
            # 停顿一下 （四四拍每秒两个音，每个音节中间稍微停顿一下）
            utime.sleep_ms(400)
            self.buzzer.duty_u16(0)  # 设备占空比为0，即不上电
            utime.sleep_ms(100)
        self.buzzer.deinit()  # 释放PWM

class PinEFencoding:
    def __init__(self):
        self.P0 = 26
        self.P1 = 27
        self.P2 = 28 
        self.P3 = 29
        self.P4 = 4
        self.P5 = 5
        self.P6 = 6
        self.P7 = 7
        self.P8 = 8
        self.P9 = 9
        self.P10 = 10
        self.P11 = 11
        self.P12 = 12
        self.P13 = 13
        self.P14 = 14
        self.P15 = 15
        self.P16 = 16


pin=PinEFencoding()
ButtonA = Button("A")
ButtonB = Button("B")
led = Led()
i2c = I2C(1,scl=Pin(19),sda=Pin(18))
display = Display(i2c)
music = Music()
