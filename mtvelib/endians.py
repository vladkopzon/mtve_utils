def extract_range(number, start, end):
    shifted = number >> end
    masked = shifted & ((1 << start) - 1)
    return masked
