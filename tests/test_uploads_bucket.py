"""Fotos no bucket S3 (com um S3 de mentira) e o comportamento sem bucket."""

import io
from types import SimpleNamespace

import pytest
from botocore.exceptions import ClientError
from PIL import Image

from app import uploads


class FakeS3:
    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": io.BytesIO(self.objects[Key])}


def png(width: int) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, width // 2), (200, 30, 30)).save(out, "PNG")
    return out.getvalue()


@pytest.fixture()
def bucket(monkeypatch, tmp_path):
    fake = FakeS3()
    cfg = SimpleNamespace(uploads_s3_bucket="b", upload_dir=str(tmp_path))
    monkeypatch.setattr(uploads, "get_settings", lambda: cfg)
    monkeypatch.setattr(uploads, "_client", lambda: fake)
    return fake, tmp_path


def test_grava_no_bucket_e_devolve_o_mesmo_caminho_de_sempre(bucket):
    fake, folder = bucket
    path = uploads.save_bytes(b"abc", ".jpg")
    name = path.removeprefix("/uploads/")
    assert path.startswith("/uploads/") and path.endswith(".jpg")
    assert fake.objects[f"uploads/{name}"] == b"abc"
    assert not list(folder.iterdir())  # nada no disco
    assert uploads.read_bytes(name) == b"abc"


def test_foto_antiga_so_no_disco_continua_valida(bucket):
    _, folder = bucket
    (folder / "velha.jpg").write_bytes(b"velha")
    assert uploads.fetch("velha.jpg") is None  # a rota cai no disco
    assert uploads.read_bytes("velha.jpg") == b"velha"
    assert uploads.read_bytes("nao-existe.jpg") is None


def test_miniatura_e_criada_uma_vez_e_guardada_no_bucket(bucket):
    fake, _ = bucket
    name = uploads.save_bytes(png(1200), ".png").removeprefix("/uploads/")
    data, kind = uploads.fetch(name, 256)
    assert kind == "image/jpeg" and Image.open(io.BytesIO(data)).width == 256
    key = f"thumbs/256/{name.rsplit('.', 1)[0]}.jpg"
    assert key in fake.objects
    fake.objects[f"uploads/{name}"] = b""  # a segunda vez vem do cache, sem reler o original
    assert uploads.fetch(name, 256)[0] == data


def test_foto_menor_que_a_miniatura_vai_inteira(bucket):
    name = uploads.save_bytes(png(100), ".png").removeprefix("/uploads/")
    data, kind = uploads.fetch(name, 720)
    assert kind == "image/png" and Image.open(io.BytesIO(data)).width == 100


def test_nome_com_caminho_nao_sai_do_bucket(bucket):
    assert uploads.fetch("../segredo.jpg") is None
    assert uploads.fetch(".thumbs") is None


def test_sem_bucket_grava_no_disco(monkeypatch, tmp_path):
    cfg = SimpleNamespace(uploads_s3_bucket="", upload_dir=str(tmp_path))
    monkeypatch.setattr(uploads, "get_settings", lambda: cfg)
    path = uploads.save_bytes(b"x", ".png")
    assert (tmp_path / path.removeprefix("/uploads/")).read_bytes() == b"x"
    assert uploads.fetch(path.removeprefix("/uploads/")) is None
