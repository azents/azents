# JSONScalar


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------

## Example

```python
from azentspublicclient.models.json_scalar import JSONScalar

# TODO update the JSON string below
json = "{}"
# create an instance of JSONScalar from a JSON string
json_scalar_instance = JSONScalar.from_json(json)
# print the JSON string representation of the object
print(JSONScalar.to_json())

# convert the object into a dict
json_scalar_dict = json_scalar_instance.to_dict()
# create an instance of JSONScalar from a dict
json_scalar_from_dict = JSONScalar.from_dict(json_scalar_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


