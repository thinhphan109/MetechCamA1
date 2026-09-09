#pragma once
#define METECH_BOARD_READY 1
#define METECH_CAM_PWDN -1
#define METECH_CAM_RESET -1
#define METECH_CAM_SIOD 4
#define METECH_CAM_SIOC 5
#define METECH_CAM_VSYNC 6
#define METECH_CAM_HREF 7
#define METECH_CAM_Y4 8
#define METECH_CAM_Y3 9
#define METECH_CAM_Y5 10
#define METECH_CAM_Y2 11
#define METECH_CAM_Y6 12
#define METECH_CAM_PCLK 13
#define METECH_CAM_XCLK 15
#define METECH_CAM_Y9 16
#define METECH_CAM_Y8 17
#define METECH_CAM_Y7 18
// Board pinout: SD_CMD = GPIO38, SD_CLK = GPIO39, SD_DATA/D0 = GPIO40.
#define METECH_SD_CMD 38
#define METECH_SD_CLK 39
#define METECH_SD_D0 40
// GPIO2 is LED only while SD is disabled; init_sd() releases it before SD setup.
#define METECH_ONBOARD_LED 2
