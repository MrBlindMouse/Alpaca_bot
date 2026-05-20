def trunc(value, digits):
    x = 10**digits
    return int(value * x) / x
