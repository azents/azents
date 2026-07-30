# Presentation


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | 
**content** | **str** |  | 
**attachments** | **List[str]** |  | [optional] 
**file_parts** | [**List[FileOutputPart]**](FileOutputPart.md) |  | [optional] 
**requested_inference_profile** | [**RequestedInferenceProfile**](RequestedInferenceProfile.md) |  | [optional] 
**message_kind** | **str** |  | 
**provider** | **str** |  | 
**resource_label** | **str** |  | 
**resource_type** | **str** |  | 
**external_message_id** | **str** |  | 
**sender_display_name** | **str** |  | 
**author_type** | **str** |  | 
**authorization** | **str** |  | 
**body** | **str** |  | 
**original_url** | **str** |  | 
**action** | [**Action2**](Action2.md) |  | 
**message** | **str** |  | 

## Example

```python
from azentspublicclient.models.presentation import Presentation

# TODO update the JSON string below
json = "{}"
# create an instance of Presentation from a JSON string
presentation_instance = Presentation.from_json(json)
# print the JSON string representation of the object
print(Presentation.to_json())

# convert the object into a dict
presentation_dict = presentation_instance.to_dict()
# create an instance of Presentation from a dict
presentation_from_dict = Presentation.from_dict(presentation_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


