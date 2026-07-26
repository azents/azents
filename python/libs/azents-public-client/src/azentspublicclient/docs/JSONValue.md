# JSONValue


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------

## Example

```python
from azentspublicclient.models.json_value import JSONValue

# TODO update the JSON string below
json = "{}"
# create an instance of JSONValue from a JSON string
json_value_instance = JSONValue.from_json(json)
# print the JSON string representation of the object
print(JSONValue.to_json())

# convert the object into a dict
json_value_dict = json_value_instance.to_dict()
# create an instance of JSONValue from a dict
json_value_from_dict = JSONValue.from_dict(json_value_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


