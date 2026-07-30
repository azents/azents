# DockerContainerProfileSpecV1

Docker Container Profile contract version 1.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**profile_kind** | **str** |  | 
**contract_family** | **str** |  | 
**schema_version** | **int** |  | 
**runner_resources** | [**DockerContainerResources**](DockerContainerResources.md) |  | 
**network_name** | **str** |  | 

## Example

```python
from azentsadminclient.models.docker_container_profile_spec_v1 import DockerContainerProfileSpecV1

# TODO update the JSON string below
json = "{}"
# create an instance of DockerContainerProfileSpecV1 from a JSON string
docker_container_profile_spec_v1_instance = DockerContainerProfileSpecV1.from_json(json)
# print the JSON string representation of the object
print(DockerContainerProfileSpecV1.to_json())

# convert the object into a dict
docker_container_profile_spec_v1_dict = docker_container_profile_spec_v1_instance.to_dict()
# create an instance of DockerContainerProfileSpecV1 from a dict
docker_container_profile_spec_v1_from_dict = DockerContainerProfileSpecV1.from_dict(docker_container_profile_spec_v1_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


