# ManagedWork


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**status** | [**ExternalChannelWorkStatus**](ExternalChannelWorkStatus.md) |  | 
**tasks** | **List[Optional[Dict[str, object]]]** |  | 
**state_revision** | **int** |  | 
**desired_progress_revision** | **int** |  | 
**progress_projected** | **bool** |  | 
**finished_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.managed_work import ManagedWork

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedWork from a JSON string
managed_work_instance = ManagedWork.from_json(json)
# print the JSON string representation of the object
print(ManagedWork.to_json())

# convert the object into a dict
managed_work_dict = managed_work_instance.to_dict()
# create an instance of ManagedWork from a dict
managed_work_from_dict = ManagedWork.from_dict(managed_work_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


