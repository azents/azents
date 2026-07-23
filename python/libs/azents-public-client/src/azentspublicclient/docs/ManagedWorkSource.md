# ManagedWorkSource


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**url** | **str** |  | 
**label** | **str** |  | 

## Example

```python
from azentspublicclient.models.managed_work_source import ManagedWorkSource

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedWorkSource from a JSON string
managed_work_source_instance = ManagedWorkSource.from_json(json)
# print the JSON string representation of the object
print(ManagedWorkSource.to_json())

# convert the object into a dict
managed_work_source_dict = managed_work_source_instance.to_dict()
# create an instance of ManagedWorkSource from a dict
managed_work_source_from_dict = ManagedWorkSource.from_dict(managed_work_source_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


