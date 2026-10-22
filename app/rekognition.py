"""Reconhecimento facial com AWS Rekognition (Photo Finder).

Cada show tem uma coleção própria (`superfas-<id do show>`). As fotos oficiais do show são indexadas
nela e a selfie do fã é comparada com os rostos da coleção. A selfie só passa pela memória: não é gravada.
"""

import logging

from fastapi import HTTPException, status

from .config import get_settings

log = logging.getLogger("superfas.rekognition")


def enabled() -> bool:
    return get_settings().rekognition_enabled


def collection_id(event_id: str) -> str:
    return f"superfas-{event_id}"


def _client():
    if not enabled():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "O reconhecimento facial ainda não foi ligado neste servidor.")
    try:
        import boto3
    except ImportError:  # pragma: no cover
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "A biblioteca da AWS (boto3) não está instalada.")
    return boto3.client("rekognition", region_name=get_settings().aws_region)


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
