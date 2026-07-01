import random

DYNAMIC_STARTING_PORT = 49152
DYNAMIC_ENDING_PORT = 65535


def generate_code() -> int:
    """Pick a random port in the dynamic/private port range (49152-65535)."""
    return random.randint(DYNAMIC_STARTING_PORT, DYNAMIC_ENDING_PORT)
