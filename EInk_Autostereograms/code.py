import digitalio
import busio
import board
import displayio
import adafruit_imageload
import time
import json
import os

from analogio import AnalogIn
from adafruit_epd.epd import Adafruit_EPD
from adafruit_epd.il91874 import Adafruit_IL91874

spi = busio.SPI(board.SCK, MOSI=board.MOSI, MISO=board.MISO)
ecs = digitalio.DigitalInOut(board.D10)
dc = digitalio.DigitalInOut(board.D9)
srcs = digitalio.DigitalInOut(board.D8)    # can be None to use internal memory
led = digitalio.DigitalInOut(board.D13)
led.direction = digitalio.Direction.OUTPUT

print("Creating display")

display = Adafruit_IL91874(176, 264, spi,         # 2.7" Tri-color display
    cs_pin=ecs, dc_pin=dc, sramcs_pin=srcs,
    rst_pin=None, busy_pin=None)

# read buttons from ePaper shield
def read_buttons():
    with AnalogIn(board.A3) as ain:
        reading = ain.value / 65535
        if reading > 0.75:
            return None
        if reading > 0.4:
            return 4
        if reading > 0.25:
            return 3
        if reading > 0.13:
            return 2
        return 1

# display bitmap file
def display_bitmap(epd, filename):
    try:
        f = open("/" + filename, "rb")
    except OSError:
        display_message("Error: Couldn't open file " + filename)
        return

    print("File opened")
    try:
        if f.read(2) != b'BM':  # check signature
            raise BMPError("Not BitMap file")

        bmpFileSize = read_le(f.read(4))
        f.read(4)  # Read & ignore creator bytes

        bmpImageoffset = read_le(f.read(4))  # Start of image data
        headerSize = read_le(f.read(4))
        bmpWidth = read_le(f.read(4))
        # convert width to 8 pixels per byte width
        bmpWidth = (bmpWidth + 7)//8
        bmpHeight = read_le(f.read(4))
        # convert unsigned int to signed int in case there is a negative height
        if bmpHeight > 0x7fffffff:
            bmpHeight = bmpHeight - 4294967296
        flip = True
        if bmpHeight < 0:
            bmpHeight = abs(bmpHeight)
            flip = False

        print("Size: %d\nImage offset: %d\nHeader size: %d" %
              (bmpFileSize, bmpImageoffset, headerSize))
        print("Width: %d\nHeight: %d" % (bmpWidth, bmpHeight))

        if read_le(f.read(2)) != 1:
            raise BMPError("Not singleplane")
        bmpDepth = read_le(f.read(2))  # bits per pixel
        print("Bit depth: %d" % (bmpDepth))
        if bmpDepth != 1:
            raise BMPError("Not 1-bit")
        if read_le(f.read(4)) != 0:
            raise BMPError("Compressed file not supported")
        read_le(4) # SizeImage
        read_le(4) # biXPelsPerMeter
        read_le(4) # biYPelsPerMeter
        read_le(4) # biClrUsed
        read_le(4) # biClrImportant
        blackpixel = 1
        if read_le(4) != 0:
            blackpixel = 0
        print("black pixel is ",blackpixel)
        print("Image OK! Drawing...")

        rowSize = (bmpWidth + 3) & ~3  # 32-bit line boundary

        for row in range(bmpHeight):  # For each scanline...
            # blink the LED
            if row%2 == 0:
                led.value = False
            else:
                led.value = True
            if flip:  # Bitmap is stored bottom-to-top order (normal BMP)
                pos = bmpImageoffset + (bmpHeight - 1 - row) * rowSize
            else:  # Bitmap is stored top-to-bottom
                pos = bmpImageoffset + row * rowSize
            f.seek(pos)
            rowdata = f.read(bmpWidth)
            for col in range(bmpWidth):
                for b in range(8):
                    if ((rowdata[col] & (0x80 >> b) != 0 and blackpixel == 0) or
                        (rowdata[col] & (0x80 >> b) == 0 and blackpixel == 1)):
                        epd.pixel(col*8 + b, row, Adafruit_EPD.BLACK)
                    #else:
                    #   epd.pixel(col*8 + b, row, Adafruit_EPD.WHITE)
    except OSError:
        display_message("Error: couldn't read file " + filename)
    except BMPError as e:
        display_message("Error: unsupported BMP file " + filename)
    finally:
        f.close()
    print("Finished drawing")

def read_le(s):
    result = 0
    shift = 0
    for byte in bytearray(s):
        result += byte << shift
        shift += 8
    return result

class BMPError(Exception):
    pass

# alternate bitmap display method using imageload library
def display_bitmap_alternate(epd, filename):
    image, palette = adafruit_imageload.load(filename,
        bitmap=displayio.Bitmap,
        palette=displayio.Palette)
    for y in range(display.height):
        # blink the LED
        if y%2 == 0:
            led.value = True
        else:
            led.value = False
        for x in range(display.width):
            if image[x,y] == 0:
                epd.pixel(x,y,Adafruit_EPD.BLACK)

# display message both on the screen and the serial port
def display_message(message):
    print(message)
    display.rotation = 1
    display.fill_rect(0,10,264,20,Adafruit_EPD.WHITE)
    display.text(message, 10, 10, Adafruit_EPD.BLACK)
    display.display()

# slide show routine
def show_files():
    try:
        filelist = os.listdir(config["slidefolder"])
        display.rotation = 1
        led.value = True
        #try:
        while True:
            for file in filelist:
                starttime = time.monotonic()
                display.fill(Adafruit_EPD.WHITE)
                print("displaying file",config["slidefolder"] + "/" + file)
                display_bitmap(display,config["slidefolder"] + "/" + file)
                #display_bitmap_alternate(display,config["slidefolder"] + "/" + file)
                endtime = time.monotonic()
                minutes = (endtime - starttime)//60
                seconds = int(endtime - starttime) - minutes*60
                print("update time:",minutes,"minutes",seconds,"seconds")
                print("updating display")
                display.display()
                print("done")
                time.sleep(5)
    except (ValueError, Exception) as e:
        display_message("Error: " + file + " " + e.args[0])
    led.value = False
    return

# run specified job
def run_job(jobfile):
    try:
        print("running job " + jobfile)
        fp = open(config["jobfolder"] + "/" + jobfile, mode='r')
        job = json.load(fp)
        fp.close()
        print("image: ", job["image"])

        starttime = time.monotonic()
        pixelsize = job["bkpixelsize"]
        whitepct = job["bkratio"]

        panelcount = 6
        led.value = True


        display.rotation = 1
        display.fill(Adafruit_EPD.WHITE)
        print("ePaper display size:",display.width,display.height);
        print(config["imagefolder"] + "/" + job["image"])
        image, palette = adafruit_imageload.load(config["imagefolder"] + "/" + job["image"],
            bitmap=displayio.Bitmap,
            palette=displayio.Palette)

        inverse = False
        print("image size:",image.width, image.height)
        if image[0] == 1:
            inverse = True
            print("using inverse image")
        panelwidth = display.width // panelcount
        createfile = True
        try:
            out = open(config["asgfolder"] + "/asg" + job["image"], mode='wb')
            print("writing to file asg" + job["image"])
        except (OSError, Exception) as e:
            # readonly filesystem, do not create file
            createfile = False
        if createfile == True:
            # BMP files are all the same dimensions, just different bitmaps, writing hardcoded headers here
            # write file header (14 bytes)
            out.write(bytearray([0x42,0x4d,0xfe,0x18,0,0,0,0,0,0,0x3e,0,0,0]))
            # write image header (40 bytes)
            out.write(bytearray([0x28,0,0,0, 0x8,0x1,0,0, 0x50,0xff,0xff,0xff, 0x1,0,0x1,0,
            0,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0, 0,0,0,0]))
            # write 2 item color table (8 bytes)
            out.write(bytearray([0xff,0xff,0xff,0,0,0,0,0]))

        with open(config["bkfolder"] + "/background-" + str(whitepct) + "-" + str(pixelsize) + ".dat","rb") as fp:
            bkdata = fp.read()
            canvas = list(bkdata)

            for y in range(0,display.height):
                # blink the LED
                if y % 2 == 0:
                    led.value = True
                else:
                    led.value = False
                tcanvas = [0 for i in range(display.width+panelwidth)]
                tpanel = [0 for i in range(panelwidth)]
                for x in range(panelwidth):
                    bytepos = (x%panelwidth) // 8 + y//pixelsize * (panelwidth + 7)//8
                    bitpos = x%8
                    pixel = canvas[bytepos] & 1<<(bitpos)
                    if pixel != 0:
                        tpanel[x] = 1
                for x in range(display.width+panelwidth):
                    pixel = tpanel[x%panelwidth]
                    if pixel != 0:
                        tcanvas[x] = 1
                for x in range(0, display.width):
                    if(x % panelwidth) == 0 and x > 0:
                        for x2 in range(x, x + panelwidth):
                            tcanvas[x2] = tcanvas[x2 - panelwidth];
                        for x2 in range(panelwidth):
                            tpanel[x2] = tcanvas[x + x2 - panelwidth]
                    offset = 0
                    if x >= panelwidth//2 and x < (image.width + panelwidth//2) and y < image.height and (
                        (image[x - panelwidth//2,y] != 0 and not inverse) or (image[x - panelwidth//2,y] == 0 and inverse)):
                    #    offset = 4
                        if job["imagegrayscale"] == 0:
                            offset = job["imageheight"]
                        else:
                            offset = (image[x - panelwidth//2,y] * job["grayscalecolors"]) // 255
                    if offset != 0:
                        for x2 in range(x,display.width,panelwidth):
                            tcanvas[x2] = tcanvas[x2 + offset]
                for x in range(0, display.width):
                    # write line to eink display
                    if tcanvas[x] != 0:
                        display.pixel(x,y,Adafruit_EPD.BLACK)
                    #else:
                    #    display.pixel(x,y,Adafruit_EPD.WHITE)
                if createfile:
                    count = 0
                    for x in range(0, display.width + 7, 8):
                        value = 0
                        for b in range(8):
                            value |= (tcanvas[x+b] << 7 ) >> b
                        out.write(bytes([value]))
                        count+=1
                    # add padding to end of line
                    padding = (4 - (count%4))%4
                    for x in range(padding):
                        out.write(bytes([0]))
        if createfile:
            out.close()
        endtime = time.monotonic()
        minutes = (endtime - starttime)//60
        seconds = int(endtime - starttime) - minutes*60
        print("completion time:",minutes,"minutes",seconds,"seconds")
        print("updating display")
        display.display()
        print("done")
    except (ValueError, Exception) as e:
        display_message("Error: " + e.args[0])
    led.value = False
    return

# main routine

display.fill(Adafruit_EPD.WHITE)
with open("/config.json") as fp:
    config = json.load(fp)
    fp.close()
print("waiting for button press")

while True:

    button = read_buttons()
    if button:
        #button pressed, waiting for button release
        while read_buttons():
            time.sleep(.1)
    if not button:
        continue
    print("Button #%d pressed" % button)
    if button == 1:
        for jobfile in config["jobs"]:
            run_job(jobfile)
    if button == 2:
        show_files()
    time.sleep(0.01)