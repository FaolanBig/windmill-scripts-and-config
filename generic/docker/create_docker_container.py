#requirements:
#docker==7.1.0

import logging
import os
import docker
from typing import Any
import uuid
from docker.errors import DockerException


logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s %(message)s"
)
logger = logging.getLogger(__name__)

def main(
    ct_image: str,
    ct_command: str | None = None,
    ct_environment: dict[str, str] | None = None,
    ct_ports: dict[str, Any] | None = None,
    ct_labels = {
        "managed-by": "windmill",
        "windmill.deployment.auto": "true"
    },
    ct_memory_limit = "128m",
    ct_nano_cpus = 1_000_000_000,
    ct_pids_limit = 256,
    ct_cap_drop = ["ALL"],
    ct_security_opt = ["no-new-privileges:true"],
    ct_auto_remove = False
) -> dict[str, str]:

    if not ct_image:
        logger.warning("Docker container creation rejected: image is required and missing")
        return {
            "finished_successful": "false",
            "error_message": "Docker image is required and missing"
        }

    logger.info("Creating Docker container from image %s", ct_image)
    host = os.environ.get("DOCKER_HOST") or "tcp://docker-test-daemon:2375"
    client = None

    try:
        client = docker.DockerClient(
            base_url=host,
            tls=False,
            timeout=30
        )
        logger.debug("Connecting to Docker daemon at %s", host)
        client.ping()

        logger.info("Pulling Docker image %s", ct_image)
        ct_pulled_image = client.images.pull(ct_image)

        logger.info("Starting Docker container %s", str(uuid.uuid4().hex))
        ct_container = client.containers.run(
            image=ct_pulled_image,
            name=str(uuid.uuid4().hex),
            command=ct_command,
            environment=ct_environment,
            ports=ct_ports,
            detach=True,
            labels=ct_labels,
            mem_limit=ct_memory_limit,
            nano_cpus=ct_nano_cpus,
            pids_limit=ct_pids_limit,
            cap_drop=ct_cap_drop,
            security_opt=ct_security_opt,
            auto_remove=ct_auto_remove
        )

        logger.info(
            "Docker container created: id=%s name=%s image_id=%s",
            ct_container.id,
            ct_container.name,
            ct_pulled_image.id
        )
        return {
            "finished_successful": "true",
            "error_message": "",
            "container_id": as_string(ct_container.id),
            "container_name": as_string(ct_container.name),
            "image_id": as_string(ct_pulled_image.id)
        }
    except DockerException as exc:
        logger.exception("Failed to create Docker container from image %s", ct_image)
        return {
            "finished_successful": "false",
            "error_message": f"Could not create Docker container: {exc}",
            "container_id": "",
            "container_name": "",
            "image_id": ""
        }
    finally:
        if client is not None:
            client.close()

def as_string(value: Any) -> str:
    return "" if value is None else str(value)