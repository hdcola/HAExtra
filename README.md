# HAExtra
自用的HA扩展组件

## saswell温控器

支持设备：

* SAS920FHL-7W-WIFI 适用于电暖
* SAS920WHL-7W-WIFI 适用于水暖

### 安装
将```saswell.py```复制到```custom_components/climate/```目录下重启hass

### 配置

```
climate:
  - platform: saswell
    username: your_username
    password: your_password
    scan_interval: 300
```

* scan_interval : 同步周期，默认五分钟

### 版权说明

本自定组件来自于Yonsm的saswell组件 [https://github.com/Yonsm/HAExtra/blob/master/custom_components/climate/saswell.py] ，我主要修改了服务器返回空的status的问题，同时对于使用多个saswell时index为序列号时带来的混乱问题。

## 中弘中央空调网关

支持设备：

* 中弘网关

空调：

* 大金VRV中央空调

### 安装

将```zhonghong.py```复制到```custom_components/climate/```目录下重启hass

### 配置

```
climate:
  - platform: zhonghong
    host: your_hub_ip
```

### 版权说明

本自定组件来自于roiff的zhonghong组件 [https://bbs.hassbian.com/thread-3831-1-1.html]
