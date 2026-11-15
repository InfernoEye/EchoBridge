"""Read the Windows Vulkan loader to show real GPU names in EchoBridge.

No SDK, vulkaninfo binary, model download, or cloud request is required.
The returned index is the Vulkan physical-device order, used by whisper.cpp's
Vulkan backend on Windows. Check that the chosen binary exposes the same order.
"""
from __future__ import annotations

from dataclasses import dataclass
import ctypes
import sys


AMD = 0x1002
NVIDIA = 0x10DE


@dataclass(frozen=True)
class GPU:
    index: int
    name: str
    vendor_id: int
    device_id: int
    kind: str

    @property
    def identity(self) -> str:
        return f'{self.vendor_id:04x}:{self.device_id:04x}:{self.name.casefold()}'

    @property
    def label(self) -> str:
        return self.name + f'  ·  GPU {self.index}'


class VkInstanceCreateInfo(ctypes.Structure):
    _fields_ = [
        ('sType', ctypes.c_uint32),
        ('pNext', ctypes.c_void_p),
        ('flags', ctypes.c_uint32),
        ('pApplicationInfo', ctypes.c_void_p),
        ('enabledLayerCount', ctypes.c_uint32),
        ('ppEnabledLayerNames', ctypes.c_void_p),
        ('enabledExtensionCount', ctypes.c_uint32),
        ('ppEnabledExtensionNames', ctypes.c_void_p),
    ]


def parse_properties(data: bytes, index: int) -> GPU:
    """VkPhysicalDeviceProperties begins with five uint32s and deviceName[256]."""
    if len(data) < 276:
        raise ValueError('Truncated Vulkan device properties')
    vendor = int.from_bytes(data[8:12], 'little')
    device = int.from_bytes(data[12:16], 'little')
    kind_code = int.from_bytes(data[16:20], 'little')
    name = data[20:276].split(b'\0', 1)[0].decode('utf-8', 'replace').strip()
    if not name:
        name = f'Unknown Vulkan GPU {index}'
    kind = {1: 'integrated', 2: 'discrete', 3: 'virtual', 4: 'cpu'}.get(kind_code, 'other')
    return GPU(index=index, name=name, vendor_id=vendor, device_id=device, kind=kind)


def detect_gpus() -> list[GPU]:
    """Enumerate Vulkan physical devices in their Vulkan index order.

    Always destroy the VkInstance; never keep a GPU context running at idle.
    """
    if sys.platform != 'win32':
        return []
    try:
        vk = ctypes.WinDLL('vulkan-1.dll')
    except OSError as exc:
        raise RuntimeError('Vulkan loader not found. Install the graphics driver for your GPU.') from exc

    vk.vkCreateInstance.argtypes = [ctypes.POINTER(VkInstanceCreateInfo), ctypes.c_void_p,
                                    ctypes.POINTER(ctypes.c_void_p)]
    vk.vkCreateInstance.restype = ctypes.c_int
    vk.vkDestroyInstance.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    vk.vkDestroyInstance.restype = None
    vk.vkEnumeratePhysicalDevices.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32),
                                               ctypes.POINTER(ctypes.c_void_p)]
    vk.vkEnumeratePhysicalDevices.restype = ctypes.c_int
    vk.vkGetPhysicalDeviceProperties.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    vk.vkGetPhysicalDeviceProperties.restype = None

    create_info = VkInstanceCreateInfo()
    create_info.sType = 1  # VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO
    instance = ctypes.c_void_p()
    result = vk.vkCreateInstance(ctypes.byref(create_info), None, ctypes.byref(instance))
    if result != 0 or not instance.value:
        raise RuntimeError(f'Could not initialize Vulkan (error {result}). Update your graphics driver.')
    try:
        count = ctypes.c_uint32()
        result = vk.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), None)
        if result != 0:
            raise RuntimeError(f'Could not enumerate Vulkan GPUs (error {result}).')
        if count.value > 64:
            raise RuntimeError('Vulkan returned an unexpected number of devices.')
        if count.value == 0:
            return []
        handles = (ctypes.c_void_p * count.value)()
        result = vk.vkEnumeratePhysicalDevices(instance, ctypes.byref(count), handles)
        if result not in (0, 5):  # VK_SUCCESS, VK_INCOMPLETE
            raise RuntimeError(f'Could not inspect Vulkan GPUs (error {result}).')
        gpus = []
        for i, handle in enumerate(handles[:count.value]):
            # The struct is currently under 1 KB. A larger buffer supports
            # future extensions and avoids marshaling private Vulkan headers.
            properties = ctypes.create_string_buffer(4096)
            vk.vkGetPhysicalDeviceProperties(handle, ctypes.byref(properties))
            gpu = parse_properties(properties.raw, i)
            if gpu.kind in ('integrated', 'discrete'):
                gpus.append(gpu)
        return gpus
    finally:
        vk.vkDestroyInstance(instance, None)


def for_backend(gpus: list[GPU], backend: str) -> list[GPU]:
    vendor = {'amd': AMD, 'nvidia': NVIDIA}.get(str(backend))
    if vendor is None:
        return []
    return [gpu for gpu in gpus if gpu.vendor_id == vendor]


def resolve_choice(gpus: list[GPU], backend: str, saved_identity: str = '', legacy_index: int = 0) -> GPU:
    """Do not silently route inference to the wrong vendor or a removed GPU."""
    available = for_backend(gpus, backend)
    if not available:
        raise RuntimeError(f'No {backend.upper()} Vulkan GPU was detected. Select CPU or check your graphics driver.')
    if saved_identity:
        matching = [gpu for gpu in available if gpu.identity == saved_identity]
        if not matching:
            raise RuntimeError('The selected GPU is missing or changed. Open Settings > AI Models and choose your graphics card again.')
        return matching[0]
    return next((gpu for gpu in available if gpu.index == legacy_index), available[0])


def selected_gpu_index(settings, backend: str, detector=detect_gpus) -> int:
    """Re-resolve by name before each task so reordered Vulkan indices are safe."""
    if backend == 'cpu':
        return 0
    identity = str(settings.value('vulkan_gpu_identity', '') or '')
    saved = int(settings.value('vulkan_device', 0))
    gpu = resolve_choice(detector(), backend, identity, saved)
    settings.setValue('vulkan_device', gpu.index)
    settings.setValue('vulkan_gpu_identity', gpu.identity)
    return gpu.index
