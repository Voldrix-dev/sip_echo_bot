import asyncio
import logging

from baresip import Config, Runtime

logging.basicConfig(level=logging.DEBUG)


async def main():
    config = Config(video_source="v4l2,/dev/video1", native_log_level="debug")
    runtime = Runtime()
    await runtime.start(config=config)
    print("Runtime started with v4l2 /dev/video1")
    await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
