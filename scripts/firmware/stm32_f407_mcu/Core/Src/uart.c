#include "uart.h"
#include "usart.h"

#define UART1_RX_BUFFER_SIZE 256U

static uint8_t s_uart1_rx_buffer[UART1_RX_BUFFER_SIZE];
static volatile uint16_t s_uart1_rx_head = 0U;
static volatile uint16_t s_uart1_rx_tail = 0U;
static uint8_t s_uart1_rx_byte = 0U;

static uint16_t UART1_NextIndex(uint16_t index)
{
  return (uint16_t)((index + 1U) % UART1_RX_BUFFER_SIZE);
}

static void UART1_BufferReset(void)
{
  s_uart1_rx_head = 0U;
  s_uart1_rx_tail = 0U;
}

static void UART1_BufferPush(uint8_t byte)
{
  uint16_t next = UART1_NextIndex(s_uart1_rx_head);

  if (next != s_uart1_rx_tail)
  {
    s_uart1_rx_buffer[s_uart1_rx_head] = byte;
    s_uart1_rx_head = next;
  }
}

static uint8_t UART1_BufferPop(void)
{
  uint8_t byte = s_uart1_rx_buffer[s_uart1_rx_tail];

  s_uart1_rx_tail = UART1_NextIndex(s_uart1_rx_tail);
  return byte;
}

void UART1_StartReceiveIT(void)
{
  UART1_BufferReset();

  if (HAL_UART_Receive_IT(&huart1, &s_uart1_rx_byte, 1U) != HAL_OK)
  {
    Error_Handler();
  }
}

void UART1_Init(void)
{
  MX_USART1_UART_Init();
  UART1_StartReceiveIT();
}

HAL_StatusTypeDef UART1_Send(const uint8_t *data, uint16_t len, uint32_t timeout)
{
  return HAL_UART_Transmit(&huart1, (uint8_t *)data, len, timeout);
}

uint16_t UART1_Available(void)
{
  uint16_t head = s_uart1_rx_head;
  uint16_t tail = s_uart1_rx_tail;

  if (head >= tail)
  {
    return (uint16_t)(head - tail);
  }

  return (uint16_t)(UART1_RX_BUFFER_SIZE - tail + head);
}

uint16_t UART1_Read(uint8_t *data, uint16_t len)
{
  uint16_t count = 0U;

  while (count < len && UART1_Available() > 0U)
  {
    data[count++] = UART1_BufferPop();
  }

  return count;
}

void HAL_UART_RxCpltCallback(UART_HandleTypeDef *huart)
{
  if (huart->Instance == USART1)
  {
    UART1_BufferPush(s_uart1_rx_byte);

    if (HAL_UART_Receive_IT(&huart1, &s_uart1_rx_byte, 1U) != HAL_OK)
    {
      Error_Handler();
    }
  }
}

int __io_putchar(int ch)
{
  uint8_t c = (uint8_t)ch;

  if (ch == '\n')
  {
    uint8_t cr = '\r';
    (void)HAL_UART_Transmit(&huart1, &cr, 1U, HAL_MAX_DELAY);
  }

  (void)HAL_UART_Transmit(&huart1, &c, 1U, HAL_MAX_DELAY);
  return ch;
}

int __io_getchar(void)
{
  uint8_t ch;

  while (UART1_Read(&ch, 1U) == 0U)
  {
    __WFI();
  }

  return (int)ch;
}
