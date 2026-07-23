# ManagedWorkTask


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**title** | **str** |  | 
**status** | [**ExternalChannelWorkTaskStatus**](ExternalChannelWorkTaskStatus.md) |  | 
**details** | **str** |  | 
**output** | **str** |  | 
**sources** | [**List[ManagedWorkSource]**](ManagedWorkSource.md) |  | 

## Example

```python
from azentspublicclient.models.managed_work_task import ManagedWorkTask

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedWorkTask from a JSON string
managed_work_task_instance = ManagedWorkTask.from_json(json)
# print the JSON string representation of the object
print(ManagedWorkTask.to_json())

# convert the object into a dict
managed_work_task_dict = managed_work_task_instance.to_dict()
# create an instance of ManagedWorkTask from a dict
managed_work_task_from_dict = ManagedWorkTask.from_dict(managed_work_task_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


