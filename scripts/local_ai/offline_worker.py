"""Smoke-test an inference worker with all socket connections/DNS blocked."""
import runpy
import sys


def offline(event, args):
    if event in {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname"}:
        raise RuntimeError("Offline acceptance blocked a network request: " + event)


sys.addaudithook(offline)
worker, request = sys.argv[1:]
sys.argv = [worker, request]
runpy.run_path(worker, run_name="__main__")
