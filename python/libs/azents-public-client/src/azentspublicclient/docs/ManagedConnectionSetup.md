# ManagedConnectionSetup


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**connection** | [**ManagedConnection**](ManagedConnection.md) |  | 

## Example

```python
from azentspublicclient.models.managed_connection_setup import ManagedConnectionSetup

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedConnectionSetup from a JSON string
managed_connection_setup_instance = ManagedConnectionSetup.from_json(json)
# print the JSON string representation of the object
print(ManagedConnectionSetup.to_json())

# convert the object into a dict
managed_connection_setup_dict = managed_connection_setup_instance.to_dict()
# create an instance of ManagedConnectionSetup from a dict
managed_connection_setup_from_dict = ManagedConnectionSetup.from_dict(managed_connection_setup_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


