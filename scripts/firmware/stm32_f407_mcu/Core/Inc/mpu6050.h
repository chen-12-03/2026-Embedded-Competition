#ifndef __MPU6050_H
#define __MPU6050_H

#ifdef __cplusplus
extern "C" {
#endif

#include "i2c.h"

#define MPU6050_I2C_ADDR_0 0x68U
#define MPU6050_I2C_ADDR_1 0x69U
#define MPU6050_I2C_ADDR_AUTO 0xFFU

typedef struct
{
  I2C_HandleTypeDef *hi2c;
  uint8_t address;
  int16_t ax;
  int16_t ay;
  int16_t az;
  int16_t gx;
  int16_t gy;
  int16_t gz;
  int16_t temp;
} MPU6050_HandleTypeDef;

HAL_StatusTypeDef MPU6050_Init(MPU6050_HandleTypeDef *dev, I2C_HandleTypeDef *hi2c, uint8_t address);
HAL_StatusTypeDef MPU6050_InitAuto(MPU6050_HandleTypeDef *dev, I2C_HandleTypeDef *hi2c);
HAL_StatusTypeDef MPU6050_ReadRaw(MPU6050_HandleTypeDef *dev);

#ifdef __cplusplus
}
#endif

#endif
