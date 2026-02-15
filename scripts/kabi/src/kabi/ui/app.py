import argparse

class KabiTuiApp:
    def __init__(self, args: argparse.Namespace):
        self.args = args

    def start(self) -> None:
        print("App started")
        print(self.args)
