import sys
import os.path
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import QCheckBox, QGridLayout, QLabel, QWidget
from PyQt5 import uic
import requests
import serial
import time
import zlib
import tempfile
import serial.tools.list_ports
import esptool
import spiffsgen
import json
from esptool import ESPLoader

port_list = []
list_chk = []
repo = "https://firmware.sensor.community/airrohr/update/latest.bin"


class main_window(QtWidgets.QMainWindow):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        uic.loadUi("main_window.ui", self)
        self.create_port_list()
        self.choose_language.addItems(['EN','FR', 'DE'])
        self.Refresh_button.clicked.connect(lambda: self.check_new_ports())
        self.Flash_button.clicked.connect(lambda : self.flash_board(port_list))
        self.Erase_button.clicked.connect(lambda : self.erase_board(port_list))
        self.Conf_button.clicked.connect(lambda : self.write_config(port_list))
        self.Whole_button.clicked.connect(lambda : self.flash_board(port_list))
        self.Whole_button.clicked.connect(lambda : self.write_config(port_list))

    # create a COM port list, checkboxes according to those ports, detect the driver type
    def create_port_list(self):
        for p in serial.tools.list_ports.comports():
            port_list.append(p.device)
        port_list.sort()
        print(port_list)
        for i in range(len(port_list)):
            list_chk.append(QCheckBox(port_list[i]))
            p = serial.tools.list_ports.comports()[i]
            self.gridLayout.addWidget(list_chk[i], int(i/5), i % 5)
            if ((p.vid, p.pid) == (0x1A86, 0x7523)):
                list_chk[i].setToolTip("CH341")
                list_chk[i].setChecked(True)
            elif ((p.vid, p.pid) == (0x10c4, 0xea60)):
                list_chk[i].setToolTip("CP2102")
                list_chk[i].setChecked(True)
            else:
                list_chk[i].setToolTip("no esp detected")
                list_chk[i].setEnabled(False)


    # on click on refresh button, refresh port list
    def check_new_ports(self):
        list_chk.clear()
        port_list.clear()
        # clear the Detected COM port box
        for i in reversed(range(self.gridLayout.count())):
            widgetToRemove = self.gridLayout.itemAt(i).widget()
            # remove it from the layout list
            self.gridLayout.removeWidget(widgetToRemove)
            # remove it from the gui
            widgetToRemove.setParent(None)
        # re-create port list and checkboxes
        self.create_port_list()

    # on click on upload firmware button, write latest.bin on esp
    def flash_board(self, devices, baudrate=115200):
        
        # cache firmware from repo in a temp file
        r = requests.get(repo, stream=True)
        cachedirfirmware = tempfile.TemporaryDirectory()
        binary = open(os.path.join(cachedirfirmware.name, 'latest.bin'), 'wb')
        binary.write(r.content)
        binary.close()

        # flash each checked device
        for i in range(len(devices)):
            if (list_chk[i].isChecked() is True):
                # initiate communication with board
                self.status_update.setText("flashing device on " + devices[i])
                esp = ESPLoader.detect_chip(devices[i], baudrate, 'hard_reset', False)
                esp_on = esp.run_stub()
                chip_ID = esp_on.chip_id()
                esp_on.change_baud(460800)

                # loading firmware in mem and compressing it
                with open(os.path.join(cachedirfirmware.name, 'latest.bin'), 'rb') as fd:
                    uncimage = fd.read()

                self.status_update.setText("compressing image for " + devices[i])
                image = zlib.compress(uncimage, 9)

                # beginning flashing by blocks
                address = 0x0
                blocks = esp_on.flash_defl_begin(len(uncimage), len(image), address)

                seq = 0
                written = 0
                t = time.time()

                self.status_update.setText("begin flashing for " + devices[i])
                while len(image) > 0:
                    current_addr = address + seq * esp_on.FLASH_WRITE_SIZE
                    address = current_addr
                    block = image[0:esp_on.FLASH_WRITE_SIZE]
                    esp_on.flash_defl_block(block, seq, timeout=3.0)
                    image = image[esp_on.FLASH_WRITE_SIZE:]
                    seq += 1
                    written += len(block)
                    print("Flashing block " + str(seq))
                    self.progress.setValue(int(100*seq/25))
                t = time.time() - t
                self.status_update.setText(devices[i] + " flashed in " + str(round(t,2)))
                self.progress.setValue(0)

                # log id in csv file if ID_enabled is checked
                if (self.ID_enabled.isChecked() is True):
                    file_name = self.ID_file.text() + '.csv'
                    
                    # check if file already exist. If not, create it
                    if (os.path.isfile(file_name) == False):
                        with open(file_name, 'w') as file:
                            file.write('Sensors for ' + self.ID_file.text() +'\n')
                    with open(file_name, 'r+') as file:
                        
                        # seek last line
                        last_line = ''
                        for line in file:
                            last_line = line
                        
                        # write infos on flashed device
                        if (last_line[0] == self.ID_prefix.text()):
                            file.seek(0, 2)
                            print(last_line[1:4])

                            # if same batch, write a new line with batch, incremented sensor number, and chip id 
                            num = int(last_line[1:4]) + 1
                            num_str = str(int(num/100)) + str(int(num/10 % 10)) + str(int(num % 10))
                            file.write(self.ID_prefix.text() + num_str + '\t' + str(chip_ID) + '\n')
                        else:
                            # if new batch, write a line with new batch name
                            # then write a line with new batch, sensor number (001), and chip id
                            file.write('\nnew batch ; prefix ' + self.ID_prefix.text() + '\n')
                            file.write(self.ID_prefix.text() + '001' + '\t' + str(chip_ID) + '\n')

                # hard resetting allows to carry on other action on sensor 
                time.sleep(0.1)
                #esp_on.change_baud(115200)
                esp.hard_reset()
                esp._port.close()
                print(esp._port)
                time.sleep(0.2)

    # on click on erase firmware button, erase flash mem on esp
    def erase_board(self, devices, baudrate=115200):
        
        # erase each checked device
        for i in range(len(devices)):
            if (list_chk[i].isChecked() is True):
                # initiate communication with board
                self.status_update.setText("erasing device on " + devices[i])
                esp = esptool.ESPLoader.detect_chip(devices[i], baudrate, 'hard_reset', False)
                esp_on = esp.run_stub()
                esp_on.change_baud(460800)
                esp_on.erase_flash()
                print("device on " + devices[i] + " erased !")
                self.status_update.setText("device on " + devices[i] + " erased !")

                # hard resetting allows to carry on other action on sensor
                time.sleep(0.1)
                esp.hard_reset()
                esp._port.close()
                print(esp._port)

    # on click on config button, write json file
    def write_config(self, devices, baudrate=460800):
        # write conf for each checked device
        for i in range(len(devices)):
            if (list_chk[i].isChecked() is True):
                
                # create generic json string
                self.status_update.setText("creating json file for " + devices[i] + "...")
                configstring = '{"SOFTWARE_VERSION":"NRZ-2020-133","current_lang":"","wlanssid":"","wlanpwd":"","www_username":"admin","www_password":"","fs_ssid":"","fs_pwd":"","www_basicauth_enabled":false,"dht_read":false,"htu21d_read":false,"ppd_read":false,"sds_read":false,"pms_read":false,"hpm_read":false,"npm_read":false,"sps30_read":false,"bmp_read":false,"bmx280_read":false,"sht3x_read":false,"ds18b20_read":false,"dnms_read":false,"dnms_correction":"0.0","temp_correction":"0.0","gps_read":false,"send2dusti":true,"ssl_dusti":false,"send2madavi":true,"ssl_madavi":false,"send2sensemap":false,"send2fsapp":false,"send2aircms":false,"send2csv":false,"auto_update":true,"use_beta":false,"has_display":false,"has_sh1106":false,"has_flipped_display":false,"has_lcd1602":false,"has_lcd1602_27":false,"has_lcd2004":false,"has_lcd2004_27":false,"display_wifi_info":true,"display_device_info":true,"debug":3,"sending_intervall_ms":145000,"time_for_wifi_config":600000,"senseboxid":"","send2custom":false,"host_custom":"192.168.234.1","url_custom":"/data.php","port_custom":80,"user_custom":"","pwd_custom":"","ssl_custom":false,"send2influx":false,"host_influx":"influx.server","url_influx":"/write?db=sensorcommunity","port_influx":8086,"user_influx":"","pwd_influx":"","measurement_name_influx":"feinstaub","ssl_influx":false}'
                json_obj = json.loads(configstring)

                # load wifi creds in json
                json_obj['wlanssid'] = self.SSID_edit.text()
                json_obj['wlanpwd'] = self.Pass_edit.text()

                # load language in json
                json_obj['current_lang'] = self.choose_language.currentText()

                # load chip id in json
                init_baud = min(ESPLoader.ESP_ROM_BAUD, baudrate)
                esp = ESPLoader.detect_chip(devices[i], init_baud, 'hard_reset', False)
                print(esp.chip_id())
                json_obj['fs_ssid'] = "airRohr-" + str(esp.chip_id())

                # which PM sensor is checked ?
                if self.SDS011.isChecked():
                    json_obj['sds_read'] = True
                elif self.PMS.isChecked():
                    json_obj['pms_read'] = True
                elif self.SPS30.isChecked():
                    json_obj['sps30_read'] = True
                elif self.PPD.isChecked():
                    json_obj['sps30_read'] = True

                # which temp/hum sensor is checked ?
                if self.BMx280.isChecked():
                    json_obj['bmx280_read'] = True
                elif self.SHT3x.isChecked():
                    json_obj['sht3x_read'] = True
                elif self.HTU21D.isChecked():
                    json_obj['htu21d_read'] = True
                elif self.DHT22.isChecked():
                    json_obj['dht_read'] = True

                # which screen is checked ? todo : add no screen
                if self.LCD1602_3F.isChecked():
                    json_obj['has_lcd1602'] = True
                elif self.LCD1602_27.isChecked():
                    json_obj['has_lcd1602_27'] = True
                elif self.LCD2004_3F.isChecked():
                    json_obj['has_lcd2004'] = True
                elif self.LCD2004_27.isChecked():
                    json_obj['has_lcd2004_27'] = True
                elif self.SSD1306.isChecked():
                    json_obj['has_display'] = True

                #print(json_obj)

                # save json string in json file
                jsonFinal = json.dumps(json_obj)
                cachedirjson = tempfile.TemporaryDirectory()
                jsonfile = open(os.path.join(cachedirjson.name, 'config.json'), "w+")
                jsonfile.write(jsonFinal)
                jsonfile.close()
                self.status_update.setText("json file created ! for " + devices[i])
                
                # create temp dir for spiffs storage
                self.status_update.setText("creating spiffs for " + devices[i] + "...")
                cachedirspiffs = tempfile.TemporaryDirectory()

                # create arguments to pass to spiffsgen
                args = []
                args.extend(["spiffsgen.py",
                    "--page-size", "256",
                    "--block-size", "8192",
                    "--meta-len=0", "0x100000"])
                args.append("--no-magic-len")
                args.append("--aligned-obj-ix-tables")
                args.extend([cachedirjson.name, os.path.join(cachedirspiffs.name, 'spiffs.bin')])

                # create spiffs
                sys.argv = args
                spiffsgen.main()

                # write spiffs on chip
                esp_on = esp.run_stub()
                esp_on.change_baud(baudrate)

                self.status_update.setText("writing spiffs for " + devices[i] + "...")
                # loading spiffs in mem and "compressing" it at rate 0. rem : could it be more ? 
                # also, could we make shorter spiffs, as most of it is empty ?
                with open(os.path.join(cachedirspiffs.name, 'spiffs.bin'), 'rb') as fd:
                    uncimagespiffs = fd.read()

                imagespiffs = zlib.compress(uncimagespiffs, 0)

                # initiate communication with board
                address = 0x100000
                blocks = esp_on.flash_defl_begin(len(uncimagespiffs), len(imagespiffs), address)

                # beggining flashing conf
                seq = 0
                written = 0
                t = time.time()
                while len(imagespiffs) > 0:
                    current_addr = address + seq * esp_on.FLASH_WRITE_SIZE
                    address=current_addr
                    block = imagespiffs[0:esp_on.FLASH_WRITE_SIZE]
                    esp_on.flash_defl_block(block, seq, timeout=3.0)
                    imagespiffs = imagespiffs[esp_on.FLASH_WRITE_SIZE:]
                    seq += 1
                    written += len(block)
                    print("flashing block "+str(seq))
                    self.progress.setValue(int(100*seq/65))

                t = time.time() - t

                # hard resetting allows to carry on other action on sensor
                time.sleep(0.1)
                esp.hard_reset()
                esp._port.close()
                print(esp._port)


app = QtWidgets.QApplication(sys.argv)
app.setStyle('fusion')
# available styles : windows, windowsvista, fusion
window = main_window()
window.show()
app.exec_()
