"""Train the PayGuard model and print its evaluation metrics."""

from payguard.model import train

if __name__ == "__main__":
    meta = train()
    print("metrics:", meta["metrics"])
    print("importance:", meta["importance"])
