"""
Helper untuk menyeragamkan format response API di seluruh endpoint.

Semua endpoint yang berhasil membungkus datanya dengan success_response().
Semua endpoint yang gagal (lewat exception, ditangani di api.py) membungkus
pesan errornya dengan error_response().

Kedua helper mengembalikan tuple (status_code, payload) karena Django Ninja
mendukung return value berbentuk (status_code, data) dari sebuah endpoint.

Format response yang dihasilkan:

Sukses:
{
    "success": true,
    "message": "Course created successfully",
    "data": { ... }
}

Gagal:
{
    "success": false,
    "message": "Bukan pemilik kursus",
    "errors": null
}
"""
from typing import Any, Optional, Union


def success_response(
    data: Any = None,
    message: str = "Success",
    status_code: int = 200,
):
    return status_code, {
        "success": True,
        "message": message,
        "data": data,
    }


def error_response(
    message: str = "An error occurred",
    errors: Optional[Union[list, dict, str]] = None,
    status_code: int = 400,
):
    return status_code, {
        "success": False,
        "message": message,
        "errors": errors,
    }