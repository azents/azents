# RuntimeContainmentStatus

Derived process-containment and Runtime operation projection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**enabled** | **bool** |  | 
**applied** | **bool** |  | 
**recreation_required** | **bool** |  | 
**nested_docker_available** | **bool** |  | 
**runtime_available** | **bool** |  | 
**availability_reason_code** | **str** |  | 

## Example

```python
from azentspublicclient.models.runtime_containment_status import RuntimeContainmentStatus

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeContainmentStatus from a JSON string
runtime_containment_status_instance = RuntimeContainmentStatus.from_json(json)
# print the JSON string representation of the object
print(RuntimeContainmentStatus.to_json())

# convert the object into a dict
runtime_containment_status_dict = runtime_containment_status_instance.to_dict()
# create an instance of RuntimeContainmentStatus from a dict
runtime_containment_status_from_dict = RuntimeContainmentStatus.from_dict(runtime_containment_status_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


