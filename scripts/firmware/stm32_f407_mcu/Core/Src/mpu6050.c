#include "mpu6050.h"

#define MPU6050_WHO_AM_I      0x75U
#define MPU6050_PWR_MGMT_1    0x6BU
#define MPU6050_SMPLRT_DIV    0x19U
#define MPU6050_CONFIG        0x1AU
#define MPU6050_GYRO_CONFIG   0x1BU
#define MPU6050_ACCEL_CONFIG  0x1CU
#define MPU6050_ACCEL_XOUT_H  0x3BU
#define MPU6050_WHO_AM_I_VAL  0x68U

static HAL_StatusTypeDef MPU6050_WriteReg(MPU6050_HandleTypeDef *dev, uint8_t reg, uint8_t value)
{
  return HAL_I2C_Mem_Write(dev->hi2c, (uint16_t)(dev->address << 1), reg, I2C_MEMADD_SIZE_8BIT, &value, 1U, HAL_MAX_DELAY);
}

static HAL_StatusTypeDef MPU6050_ReadReg(MPU6050_HandleTypeDef *dev, uint8_t reg, uint8_t *value)
{
  return HAL_I2C_Mem_Read(dev->hi2c, (uint16_t)(dev->address << 1), reg, I2C_MEMADD_SIZE_8BIT, value, 1U, HAL_MAX_DELAY);
}

static HAL_StatusTypeDef MPU6050_Probe(MPU6050_HandleTypeDef *dev, uint8_t address)
{
  uint8_t who_am_i = 0U;
  HAL_StatusTypeDef status;

  dev->address = address;

  if (HAL_I2C_IsDeviceReady(dev->hi2c, (uint16_t)(address << 1), 3U, 20U) != HAL_OK)
  {
    return HAL_ERROR;
  }

  status = MPU6050_ReadReg(dev, MPU6050_WHO_AM_I, &who_am_i);
  if (status != HAL_OK)
  {
    return status;
  }

  if (who_am_i != MPU6050_WHO_AM_I_VAL)
  {
    return HAL_ERROR;
  }

  return HAL_OK;
}

HAL_StatusTypeDef MPU6050_Init(MPU6050_HandleTypeDef *dev, I2C_HandleTypeDef *hi2c, uint8_t address)
{
  if ((dev == NULL) || (hi2c == NULL))
  {
    return HAL_ERROR;
  }

  dev->hi2c = hi2c;

  if (address == MPU6050_I2C_ADDR_AUTO)
  {
    return MPU6050_InitAuto(dev, hi2c);
  }

  if (MPU6050_Probe(dev, address) != HAL_OK)
  {
    return HAL_ERROR;
  }

  if (MPU6050_WriteReg(dev, MPU6050_PWR_MGMT_1, 0x80U) != HAL_OK)
  {
    return HAL_ERROR;
  }

  HAL_Delay(100);

  if (MPU6050_WriteReg(dev, MPU6050_PWR_MGMT_1, 0x00U) != HAL_OK)
  {
    return HAL_ERROR;
  }

  if (MPU6050_WriteReg(dev, MPU6050_SMPLRT_DIV, 0x07U) != HAL_OK)
  {
    return HAL_ERROR;
  }

  if (MPU6050_WriteReg(dev, MPU6050_CONFIG, 0x03U) != HAL_OK)
  {
    return HAL_ERROR;
  }

  if (MPU6050_WriteReg(dev, MPU6050_GYRO_CONFIG, 0x00U) != HAL_OK)
  {
    return HAL_ERROR;
  }

  if (MPU6050_WriteReg(dev, MPU6050_ACCEL_CONFIG, 0x00U) != HAL_OK)
  {
    return HAL_ERROR;
  }

  return HAL_OK;
}

HAL_StatusTypeDef MPU6050_InitAuto(MPU6050_HandleTypeDef *dev, I2C_HandleTypeDef *hi2c)
{
  if ((dev == NULL) || (hi2c == NULL))
  {
    return HAL_ERROR;
  }

  dev->hi2c = hi2c;

  if (MPU6050_Probe(dev, MPU6050_I2C_ADDR_0) != HAL_OK)
  {
    if (MPU6050_Probe(dev, MPU6050_I2C_ADDR_1) != HAL_OK)
    {
      return HAL_ERROR;
    }
  }

  if (MPU6050_WriteReg(dev, MPU6050_PWR_MGMT_1, 0x80U) != HAL_OK)
  {
    return HAL_ERROR;
  }

  HAL_Delay(100);

  if (MPU6050_WriteReg(dev, MPU6050_PWR_MGMT_1, 0x00U) != HAL_OK)
  {
    return HAL_ERROR;
  }

  if (MPU6050_WriteReg(dev, MPU6050_SMPLRT_DIV, 0x07U) != HAL_OK)
  {
    return HAL_ERROR;
  }

  if (MPU6050_WriteReg(dev, MPU6050_CONFIG, 0x03U) != HAL_OK)
  {
    return HAL_ERROR;
  }

  if (MPU6050_WriteReg(dev, MPU6050_GYRO_CONFIG, 0x00U) != HAL_OK)
  {
    return HAL_ERROR;
  }

  if (MPU6050_WriteReg(dev, MPU6050_ACCEL_CONFIG, 0x00U) != HAL_OK)
  {
    return HAL_ERROR;
  }

  return HAL_OK;
}

HAL_StatusTypeDef MPU6050_ReadRaw(MPU6050_HandleTypeDef *dev)
{
  uint8_t data[14];

  if ((dev == NULL) || (dev->hi2c == NULL))
  {
    return HAL_ERROR;
  }

  if (HAL_I2C_Mem_Read(dev->hi2c, (uint16_t)(dev->address << 1), MPU6050_ACCEL_XOUT_H, I2C_MEMADD_SIZE_8BIT, data, 14U, HAL_MAX_DELAY) != HAL_OK)
  {
    return HAL_ERROR;
  }

  dev->ax = (int16_t)((uint16_t)data[0] << 8 | data[1]);
  dev->ay = (int16_t)((uint16_t)data[2] << 8 | data[3]);
  dev->az = (int16_t)((uint16_t)data[4] << 8 | data[5]);
  dev->temp = (int16_t)((uint16_t)data[6] << 8 | data[7]);
  dev->gx = (int16_t)((uint16_t)data[8] << 8 | data[9]);
  dev->gy = (int16_t)((uint16_t)data[10] << 8 | data[11]);
  dev->gz = (int16_t)((uint16_t)data[12] << 8 | data[13]);

  return HAL_OK;
}
