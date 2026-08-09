# RuntimeProfileContainmentStatus

Safe containment capabilities derived from one typed Profile.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**enabled** | **bool** |  | 
**nested_docker_available** | **bool** |  | 

## Example

```python
from azentspublicclient.models.runtime_profile_containment_status import RuntimeProfileContainmentStatus

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProfileContainmentStatus from a JSON string
runtime_profile_containment_status_instance = RuntimeProfileContainmentStatus.from_json(json)
# print the JSON string representation of the object
print(RuntimeProfileContainmentStatus.to_json())

# convert the object into a dict
runtime_profile_containment_status_dict = runtime_profile_containment_status_instance.to_dict()
# create an instance of RuntimeProfileContainmentStatus from a dict
runtime_profile_containment_status_from_dict = RuntimeProfileContainmentStatus.from_dict(runtime_profile_containment_status_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


