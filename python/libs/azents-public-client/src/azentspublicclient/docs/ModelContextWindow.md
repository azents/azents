# ModelContextWindow

Model context window capability.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**max_input_tokens** | **int** |  | [optional] 
**max_output_tokens** | **int** |  | [optional] 

## Example

```python
from azentspublicclient.models.model_context_window import ModelContextWindow

# TODO update the JSON string below
json = "{}"
# create an instance of ModelContextWindow from a JSON string
model_context_window_instance = ModelContextWindow.from_json(json)
# print the JSON string representation of the object
print(ModelContextWindow.to_json())

# convert the object into a dict
model_context_window_dict = model_context_window_instance.to_dict()
# create an instance of ModelContextWindow from a dict
model_context_window_from_dict = ModelContextWindow.from_dict(model_context_window_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


