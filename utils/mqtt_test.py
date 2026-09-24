import json
import time
import datetime
import os

import paho.mqtt.client as mqtt

Config_Error={
    "username_error": "用户名错误",
    "password_error": "密码错误",
    "addr_error": "地址报错",
    "port_error": "端口报错",
    "topic_error": "主题报错",
    "connect_error": "连接失败错误",
    "connect_success": "连接成功"
}
class mqtt_client:
    def __init__(self,username:str,addr:str,port:int,password:str,topic:str):
        self.username=username
        self.addr=addr
        self.port=port
        self.password=password
        self.topic=topic
        self.client=mqtt.Client(username)
        self.client.username_pw_set(username,password)
        self.client.connect(addr,port)
        self.client.loop_start()
        time.sleep(1)
        self.client.subscribe(topic)
        time.sleep(1)
    
    def publish(self,msg:str):
        self.client.publish(self.topic,msg)
    
    def subscribe(self,topic:str):
        self.client.subscribe(topic)
        time.sleep(1)
    
    def unsubscribe(self,topic:str):
        self.client.unsubscribe(topic)
        time.sleep(1)
    
    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()
        time.sleep(1)
    
    def connect(self):
        self.client.connect(self.addr,self.port)
        self.client.loop_start()
        time.sleep(1)
        self.client.subscribe(self.topic)
        time.sleep(1)
        print(Config_Error["connect_success"])

def main():
    client = mqtt_client("test", "192.168.1.100", 1883, "test", "test")
    try:
        client.publish("test")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()

