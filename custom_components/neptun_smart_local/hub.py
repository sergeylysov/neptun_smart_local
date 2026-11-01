from __future__ import annotations

import asyncio
import inspect
import logging

from homeassistant.core import HomeAssistant
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.framer import FramerType

_LOGGER = logging.getLogger(__name__)

DEVICE_ID = 240


def uint16_to_bits(value: int) -> list[int]:
    """Convert a 16-bit register to a list of 16 bits, index 0 = MSB (bit 15)."""
    value = int(value) & 0xFFFF
    return [(value >> (15 - i)) & 1 for i in range(16)]


def bits_to_uint16(bits) -> int:
    """Pack a sequence of bits (index 0 = MSB) into a 16-bit register value."""
    value = 0
    for bit in bits:
        value = (value << 1) | (1 if bit else 0)
    return value & 0xFFFF


def registers_to_uint32(high: int, low: int) -> int:
    return ((high & 0xFFFF) << 16) | (low & 0xFFFF)


class modbus_hub:
    def __init__(self, hass: HomeAssistant, host, port) -> None:
        self._host = host
        self._port = port
        self._hass = hass
        self._client = AsyncModbusTcpClient(
            host=host,
            port=port,
            framer=FramerType.SOCKET,
            retries=5,
            timeout=10,
            reconnect_delay=2,
        )
        self._is_connected = False
        self._request_semaphore = asyncio.Semaphore(1)

    async def connect(self):
        try:
            if not self._client.connected:
                await self._client.connect()
            self._is_connected = True
        except asyncio.CancelledError:
            _LOGGER.debug(f"Подключение к Modbus {self._host}:{self._port} было отменено")
            self._is_connected = False
            raise
        except Exception as e:
            _LOGGER.error(f"Ошибка подключения к Modbus {self._host}:{self._port}: {e}")
            self._is_connected = False
            raise ValueError(f"Не удалось подключиться к устройству: {e}")

    async def disconnect(self):
        if self._client.connected:
            # pymodbus>=3.7: close() синхронный (возвращает None) — await None
            # падал TypeError и ломал unload entry (создание options flow — первый
            # вызов reload в жизни интеграции). Совместимо и со старыми версиями.
            result = self._client.close()
            if inspect.isawaitable(result):
                await result
        self._is_connected = False

    async def _ensure_connected(self):
        if not self._client.connected:
            await self.connect()

    async def read_holding_registers(self, address, count):
        async with self._request_semaphore:
            try:
                await self._ensure_connected()
                result = await self._client.read_holding_registers(
                    address, count=count, device_id=DEVICE_ID
                )
                if result.isError():
                    _LOGGER.debug(f"Ошибка Modbus при чтении регистров {address}+{count}: {result}")
                    return None
                if result.registers and len(result.registers) >= count:
                    return list(result.registers[:count])
                return None
            except Exception as e:
                if "Not connected" in str(e) or "Connection" in str(e):
                    _LOGGER.debug(f"Ошибка подключения при чтении регистров {address}: {e}")
                else:
                    _LOGGER.debug(f"Ошибка при чтении регистров {address}: {e}")
                return None

    async def read_holding_register_uint16(self, address, count=1):
        registers = await self.read_holding_registers(address, 1)
        if registers:
            return registers[0]
        return None

    async def read_holding_register_uint32(self, address, count=2):
        registers = await self.read_holding_registers(address, 2)
        if registers and len(registers) >= 2:
            return registers_to_uint32(registers[0], registers[1])
        return None

    async def read_holding_register_bits(self, address, count=1):
        registers = await self.read_holding_registers(address, 1)
        if registers:
            return uint16_to_bits(registers[0])
        return None

    async def write_holding_register_bits(self, address, bits) -> None:
        if bits is None or len(bits) != 16:
            raise ValueError(f"Для записи регистра {address} нужно 16 бит, получено {len(bits) if bits is not None else None}")
        await self.write_holding_register(address, bits_to_uint16(bits))

    async def write_holding_register(self, address, value) -> None:
        async with self._request_semaphore:
            try:
                await self._ensure_connected()
                result = await self._client.write_register(
                    address, int(value) & 0xFFFF, device_id=DEVICE_ID
                )
                if result.isError():
                    _LOGGER.warning(f"Ошибка Modbus при записи значения {value} в регистр {address}: {result}")
                    raise Exception(f"Modbus write error: {result}")
            except Exception as e:
                _LOGGER.warning(f"Ошибка при записи значения {value} в регистр {address}: {e}")
                raise
