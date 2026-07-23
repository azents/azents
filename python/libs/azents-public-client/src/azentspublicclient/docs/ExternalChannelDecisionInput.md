# ExternalChannelDecisionInput


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**decision** | **str** |  | 
**summary** | **str** |  | [optional] 

## Example

```python
from azentspublicclient.models.external_channel_decision_input import ExternalChannelDecisionInput

# TODO update the JSON string below
json = "{}"
# create an instance of ExternalChannelDecisionInput from a JSON string
external_channel_decision_input_instance = ExternalChannelDecisionInput.from_json(json)
# print the JSON string representation of the object
print(ExternalChannelDecisionInput.to_json())

# convert the object into a dict
external_channel_decision_input_dict = external_channel_decision_input_instance.to_dict()
# create an instance of ExternalChannelDecisionInput from a dict
external_channel_decision_input_from_dict = ExternalChannelDecisionInput.from_dict(external_channel_decision_input_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


