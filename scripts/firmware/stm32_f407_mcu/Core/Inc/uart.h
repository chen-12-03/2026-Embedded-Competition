#ifndef __UART_H
#define __UART_H

#ifdef __cplusplus
extern "C" {
#endif

#include "main.h"

void UART1_Init(void);
void UART1_StartReceiveIT(void);
HAL_StatusTypeDef UART1_Send(const uint8_t *data, uint16_t len, uint32_t timeout);
uint16_t UART1_Read(uint8_t *data, uint16_t len);
uint16_t UART1_Available(void);

#ifdef __cplusplus
}
#endif

#endif
