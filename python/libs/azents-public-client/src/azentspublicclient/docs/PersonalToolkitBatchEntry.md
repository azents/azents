# PersonalToolkitBatchEntry

One exact connection in an atomic multi-connection save.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_mode** | [**PersonalToolkitAccessMode**](PersonalToolkitAccessMode.md) |  | 
**mode** | [**PersonalToolkitAccessMode**](PersonalToolkitAccessMode.md) |  | 
**allow_agent_ids** | **List[str]** |  | 
**restrict_agent_ids** | **List[str]** |  | 
**toolkit_id** | **str** |  | 

## Example

```python
from azentspublicclient.models.personal_toolkit_batch_entry import PersonalToolkitBatchEntry

# TODO update the JSON string below
json = "{}"
# create an instance of PersonalToolkitBatchEntry from a JSON string
personal_toolkit_batch_entry_instance = PersonalToolkitBatchEntry.from_json(json)
# print the JSON string representation of the object
print(PersonalToolkitBatchEntry.to_json())

# convert the object into a dict
personal_toolkit_batch_entry_dict = personal_toolkit_batch_entry_instance.to_dict()
# create an instance of PersonalToolkitBatchEntry from a dict
personal_toolkit_batch_entry_from_dict = PersonalToolkitBatchEntry.from_dict(personal_toolkit_batch_entry_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


