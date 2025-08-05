# ruff: noqa: N816, ANN201, D103, N806, ANN001, N803
# By https://github.com/googollee/eviltransform/blob/master/python/eviltransform/__init__.py#L61-L66

import math

earthR = 6378137.0


def transform(x, y):
    xy = x * y
    absX = math.sqrt(abs(x))
    xPi = x * math.pi
    yPi = y * math.pi
    d = 20.0 * math.sin(6.0 * xPi) + 20.0 * math.sin(2.0 * xPi)

    lat = d
    lng = d

    lat += 20.0 * math.sin(yPi) + 40.0 * math.sin(yPi / 3.0)
    lng += 20.0 * math.sin(xPi) + 40.0 * math.sin(xPi / 3.0)

    lat += 160.0 * math.sin(yPi / 12.0) + 320 * math.sin(yPi / 30.0)
    lng += 150.0 * math.sin(xPi / 12.0) + 300.0 * math.sin(xPi / 30.0)

    lat *= 2.0 / 3.0
    lng *= 2.0 / 3.0

    lat += -100.0 + 2.0 * x + 3.0 * y + 0.2 * y * y + 0.1 * xy + 0.2 * absX
    lng += 300.0 + x + 2.0 * y + 0.1 * x * x + 0.1 * xy + 0.1 * absX

    return lat, lng


def delta(lat, lng):
    ee = 0.00669342162296594323
    dLat, dLng = transform(lng - 105.0, lat - 35.0)
    radLat = lat / 180.0 * math.pi
    magic = math.sin(radLat)
    magic = 1 - ee * magic * magic
    sqrtMagic = math.sqrt(magic)
    dLat = (dLat * 180.0) / ((earthR * (1 - ee)) / (magic * sqrtMagic) * math.pi)
    dLng = (dLng * 180.0) / (earthR / sqrtMagic * math.cos(radLat) * math.pi)
    return dLat, dLng


def gcj2wgs(gcjLat, gcjLng):
    dlat, dlng = delta(gcjLat, gcjLng)
    return gcjLat - dlat, gcjLng - dlng
