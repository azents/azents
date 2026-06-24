import datetime
from typing import IO, Any

from botocore.exceptions import ClientError as BotoClientError
from types_aiobotocore_s3.client import S3Client


class S3Service:
    """파일 작업을 위한 S3 서비스."""

    def __init__(
        self, s3_client: S3Client, public_s3_client: S3Client | None = None
    ) -> None:
        """
        S3 서비스 초기화.

        :param s3_client: 내부 작업용 S3 클라이언트
        :param public_s3_client: 공개 작업용 S3 클라이언트 (예: presigned URL).
            None이면 s3_client 사용.
        """
        self.s3_client = s3_client
        self.public_s3_client = public_s3_client or s3_client

    async def upload(
        self,
        bucket: str,
        key: str,
        body: str | bytes | IO[str] | IO[bytes],
        *,
        content_type: str | None = None,
    ) -> None:
        """
        S3에 파일 업로드.

        :param bucket: S3 bucket 이름
        :param key: S3 object key
        :param body: 파일 내용
        :param content_type: Content type (선택)
        """
        args: dict[str, Any] = {
            "Bucket": bucket,
            "Key": key,
            "Body": body,
        }
        if content_type:
            args["ContentType"] = content_type
        await self.s3_client.put_object(**args)

    async def download_bytes(self, bucket: str, key: str) -> bytes | None:
        """
        S3에서 bytes 다운로드.

        :param bucket: S3 bucket 이름
        :param key: S3 object key
        :return: bytes로 된 파일 내용, 없으면 None
        """
        try:
            response = await self.s3_client.get_object(Bucket=bucket, Key=key)
        except BotoClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"NoSuchKey", "404"}:
                return None
            raise
        body = await response["Body"].read()
        return bytes(body)

    async def copy(
        self,
        destination_bucket: str,
        destination_key: str,
        source_bucket: str,
        source_key: str,
    ) -> None:
        """
        S3 내에서 파일 복사.

        :param destination_bucket: 대상 bucket 이름
        :param destination_key: 대상 object key
        :param source_bucket: 원본 bucket 이름
        :param source_key: 원본 object key
        """
        await self.s3_client.copy_object(
            Bucket=destination_bucket,
            Key=destination_key,
            CopySource={"Bucket": source_bucket, "Key": source_key},
        )

    async def delete(self, bucket: str, key: str) -> None:
        """
        S3에서 파일 삭제.

        :param bucket: S3 bucket 이름
        :param key: S3 object key
        """
        await self.s3_client.delete_object(Bucket=bucket, Key=key)

    async def move(
        self,
        destination_bucket: str,
        destination_key: str,
        source_bucket: str,
        source_key: str,
    ) -> None:
        """
        S3 내에서 파일 이동.

        :param destination_bucket: 대상 bucket 이름
        :param destination_key: 대상 object key
        :param source_bucket: 원본 bucket 이름
        :param source_key: 원본 object key
        """
        await self.copy(
            destination_bucket=destination_bucket,
            destination_key=destination_key,
            source_bucket=source_bucket,
            source_key=source_key,
        )
        await self.delete(bucket=source_bucket, key=source_key)

    async def get_download_url(
        self,
        bucket: str,
        key: str,
        expires_in: datetime.timedelta,
    ) -> str:
        """
        S3에서 파일 다운로드용 presigned URL 생성.

        :param bucket: S3 bucket 이름
        :param key: S3 object key
        :param expires_in: URL 만료 시간
        :return: Presigned URL
        """
        return await self.public_s3_client.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": bucket,
                "Key": key,
            },
            ExpiresIn=int(expires_in.total_seconds()),
        )

    async def get_upload_url(
        self,
        bucket: str,
        key: str,
        content_type: str,
        expires_in: datetime.timedelta,
    ) -> str:
        """
        S3 업로드용 presigned URL (PUT) 생성.

        클라이언트가 브라우저에서 직접 PUT 요청을 보낼 수 있도록 URL 을 발급한다.
        presigned URL 이 특정 ``content_type`` 으로 바인딩되므로 클라이언트는
        동일 ``Content-Type`` 헤더로 업로드해야 한다.

        :param bucket: S3 bucket 이름
        :param key: S3 object key
        :param content_type: 업로드될 파일 MIME type
        :param expires_in: URL 만료 시간
        :return: Presigned PUT URL
        """
        return await self.public_s3_client.generate_presigned_url(
            ClientMethod="put_object",
            Params={
                "Bucket": bucket,
                "Key": key,
                "ContentType": content_type,
            },
            ExpiresIn=int(expires_in.total_seconds()),
        )

    async def exists(self, bucket: str, key: str) -> bool:
        """
        S3에 파일이 존재하는지 확인.

        :param bucket: S3 bucket 이름
        :param key: S3 object key
        :return: 파일 존재 여부
        """
        try:
            await self.s3_client.head_object(Bucket=bucket, Key=key)
            return True
        except self.s3_client.exceptions.ClientError as e:
            if e.response.get("Error", {}).get("Code") == "404":
                return False
            raise

    async def list_keys(self, bucket: str, prefix: str) -> list[str]:
        """
        S3 bucket에서 prefix로 시작하는 모든 object key 목록 반환.

        :param bucket: S3 bucket 이름
        :param prefix: key prefix
        :return: object key 목록
        """
        keys: list[str] = []
        paginator = self.s3_client.get_paginator("list_objects_v2")
        async for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                key = obj.get("Key")
                if key is not None:
                    keys.append(key)
        return keys

    async def delete_by_prefix(self, bucket: str, prefix: str) -> int:
        """
        S3 bucket에서 prefix로 시작하는 모든 object 삭제.

        :param bucket: S3 bucket 이름
        :param prefix: key prefix
        :return: 삭제된 object 수
        """
        keys = await self.list_keys(bucket, prefix)
        if not keys:
            return 0

        # S3 delete_objects는 한 번에 최대 1000개까지 삭제 가능
        deleted_count = 0
        for i in range(0, len(keys), 1000):
            batch = keys[i : i + 1000]
            await self.s3_client.delete_objects(
                Bucket=bucket,
                Delete={"Objects": [{"Key": key} for key in batch]},
            )
            deleted_count += len(batch)

        return deleted_count
