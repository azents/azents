# DockerContainerResources

Docker-native enforceable Runner resource choices.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**cpu_reservation_millicores** | **int** |  | 
**cpu_limit_millicores** | **int** |  | 
**memory_reservation_bytes** | **int** |  | 
**memory_limit_bytes** | **int** |  | 

## Example

```python
from azentspublicclient.models.docker_container_resources import DockerContainerResources

# TODO update the JSON string below
json = "{}"
# create an instance of DockerContainerResources from a JSON string
docker_container_resources_instance = DockerContainerResources.from_json(json)
# print the JSON string representation of the object
print(DockerContainerResources.to_json())

# convert the object into a dict
docker_container_resources_dict = docker_container_resources_instance.to_dict()
# create an instance of DockerContainerResources from a dict
docker_container_resources_from_dict = DockerContainerResources.from_dict(docker_container_resources_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


