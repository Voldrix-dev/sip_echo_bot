import time
import pylinphone

def main():
    # Инициализация фабрики и ядра Linphone
    factory = pylinphone.Factory.get()
    core = factory.create_core(None, None, None)
    
    # Включаем видеозахват
    core.video_capture_enabled = True
    core.video_display_enabled = True
    
    # Выводим список доступных камер для проверки
    print("Доступные видеоустройства:")
    for device in core.video_devices:
        print(f" - {device}")
        
    # Выбираем нашу виртуальную камеру
    # На Linux это может быть: "V4L2: /dev/video50"
    # На Windows: "OBS Virtual Camera"
    target_camera = "V4L2: /dev/video50" 
    
    if target_camera in core.video_devices:
        core.video_device = target_camera
        print(f"\nУспешно установлена камера: {core.video_device}")
    else:
        print(f"\nКамера {target_camera} не найдена. Используется по умолчанию: {core.video_device}")

    # Пример запуска основного цикла для совершения/приема звонков
    print("Ядро Linphone запущено. Ожидание...")
    try:
        while True:
            core.iterate() # Обновление состояния SIP-клиента
            time.sleep(0.02)
    except KeyboardInterrupt:
        print("Выключение...")

if __name__ == "__main__":
    main()
