"""Reconhecimento facial com AWS Rekognition (Photo Finder).

Cada show tem uma coleção própria (`superfas-<id do show>`). As fotos oficiais do show são indexadas
nela e a selfie do fã é comparada com os rostos da coleção. A selfie só passa pela memória: não é gravada.
"""

import logging

from fastapi import HTTPException, status

from .config import get_settings

log = logging.getLogger("superfas.rekognition")


def aws_kwargs() -> dict:
    """Região e, se estiverem na configuração (.env), as chaves da AWS. O .env não vira variável de ambiente,
    então sem isto o boto3 usaria as credenciais de outra conta que estiverem no computador."""
    cfg = get_settings()
    kw: dict = {"region_name": cfg.aws_region}
    if cfg.aws_access_key_id and cfg.aws_secret_access_key:
        kw["aws_access_key_id"] = cfg.aws_access_key_id
        kw["aws_secret_access_key"] = cfg.aws_secret_access_key
    return kw


def enabled() -> bool:
    return get_settings().rekognition_enabled


def shared_enabled() -> bool:
    """Há uma coleção e um bucket configurados (fotos já indexadas fora do Super Fãs)."""
    s = get_settings()
    return s.rekognition_enabled and bool(s.rekognition_collection_id and s.s3_bucket)


def collection_id(event_id: str) -> str:
    return f"superfas-{event_id}"


def _client():
    if not enabled():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "O reconhecimento facial ainda não foi ligado neste servidor.")
    try:
        import boto3
    except ImportError:  # pragma: no cover
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "A biblioteca da AWS (boto3) não está instalada.")
    return boto3.client("rekognition", **aws_kwargs())


def _aws_error(exc: Exception) -> HTTPException:
    log.exception("Falha ao falar com o AWS Rekognition")
    return HTTPException(status.HTTP_502_BAD_GATEWAY, "Não foi possível falar com o reconhecimento facial agora. Tente de novo em instantes.")


def index_photo(event_id: str, photo_id: str, data: bytes) -> list[str]:
    """Indexa os rostos de uma foto do show e devolve os ids dos rostos."""
    client = _client()
    try:
        try:
            client.create_collection(CollectionId=collection_id(event_id))
        except client.exceptions.ResourceAlreadyExistsException:
            pass
        res = client.index_faces(
            CollectionId=collection_id(event_id),
            Image={"Bytes": data},
            ExternalImageId=photo_id,
            MaxFaces=50,
            QualityFilter="AUTO",
        )
    except client.exceptions.InvalidImageFormatException:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Formato de imagem não aceito pelo reconhecimento facial (use JPG ou PNG).")
    except Exception as exc:  # noqa: BLE001
        raise _aws_error(exc)
    return [r["Face"]["FaceId"] for r in res.get("FaceRecords", [])]


def search_selfie(event_id: str, data: bytes) -> list[str]:
    """Ids das fotos do show em que aparece o rosto da selfie (sem repetir)."""
    client = _client()
    try:
        res = client.search_faces_by_image(
            CollectionId=collection_id(event_id),
            Image={"Bytes": data},
            FaceMatchThreshold=get_settings().rekognition_threshold,
            MaxFaces=100,
            QualityFilter="AUTO",
        )
    except client.exceptions.ResourceNotFoundException:
        return []  # ainda não há fotos indexadas deste show
    except client.exceptions.InvalidParameterException:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Não encontramos um rosto na selfie. Tente com mais luz, de frente e sem óculos escuros.")
    except client.exceptions.InvalidImageFormatException:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Envie a selfie em JPG ou PNG.")
    except Exception as exc:  # noqa: BLE001
        raise _aws_error(exc)
    ids: list[str] = []
    for match in res.get("FaceMatches", []):
        photo_id = match["Face"].get("ExternalImageId")
        if photo_id and photo_id not in ids:
            ids.append(photo_id)
    return ids


def delete_faces(event_id: str, face_ids: list[str]) -> None:
    """Tira os rostos de uma foto apagada da coleção (se der erro, só registra)."""
    if not face_ids or not enabled():
        return
    try:
        _client().delete_faces(CollectionId=collection_id(event_id), FaceIds=face_ids)
    except Exception:  # noqa: BLE001
        log.exception("Não foi possível apagar rostos do Rekognition")


def search_shared(data: bytes) -> list[str]:
    """Procura o rosto da selfie na coleção configurada e devolve o ExternalImageId de cada foto (sem repetir)."""
    cfg = get_settings()
    client = _client()
    try:
        res = client.search_faces_by_image(
            CollectionId=cfg.rekognition_collection_id,
            Image={"Bytes": data},
            FaceMatchThreshold=cfg.rekognition_threshold,
            MaxFaces=100,
            QualityFilter="AUTO",
        )
    except client.exceptions.ResourceNotFoundException:
        log.error("Coleção %s não encontrada na região %s", cfg.rekognition_collection_id, cfg.aws_region)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "A coleção de fotos não foi encontrada. Avise a equipe.")
    except client.exceptions.InvalidParameterException:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Não encontramos um rosto na selfie. Tente com mais luz, de frente e sem óculos escuros.")
    except client.exceptions.InvalidImageFormatException:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Envie a selfie em JPG ou PNG.")
    except Exception as exc:  # noqa: BLE001
        raise _aws_error(exc)
    ids: list[str] = []
    for match in res.get("FaceMatches", []):
        photo_id = match["Face"].get("ExternalImageId")
        if photo_id and photo_id not in ids:
            ids.append(photo_id)
    log.info("Photo Finder: %d rostos parecidos, %d fotos. Exemplos de ExternalImageId: %s", len(res.get("FaceMatches", [])), len(ids), ids[:3])
    return ids


def photo_key(external_id: str) -> str:
    """Caminho da foto no bucket. Se o ExternalImageId já for um caminho (tem "/"), usa ele; senão monta prefixo + id + sufixo."""
    cfg = get_settings()
    if "/" in external_id:
        return external_id
    return f"{cfg.s3_photo_prefix}{external_id}{cfg.s3_photo_suffix}"


def presigned_photos(external_ids: list[str]) -> list[tuple[str, str]]:
    """(ExternalImageId, link temporário do S3) de cada foto que existe no bucket."""
    import boto3
    from botocore.exceptions import ClientError

    cfg = get_settings()
    s3 = boto3.client("s3", **aws_kwargs())
    out: list[tuple[str, str]] = []
    for ext in external_ids:
        key = photo_key(ext)
        try:
            s3.head_object(Bucket=cfg.s3_bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                log.warning("Foto %s não existe no bucket %s", key, cfg.s3_bucket)
                continue  # o rosto está na coleção, mas a foto não está nesse caminho
        try:
            url = s3.generate_presigned_url(
                "get_object", Params={"Bucket": cfg.s3_bucket, "Key": key}, ExpiresIn=cfg.presigned_url_expires_seconds
            )
        except Exception:  # noqa: BLE001
            log.exception("Não foi possível gerar o link da foto %s", key)
            continue
        out.append((ext, url))
    return out
