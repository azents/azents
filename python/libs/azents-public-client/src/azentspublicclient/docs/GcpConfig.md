# GcpConfig

Google Vertex AI settings, stored as plaintext.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'gcp_service_account']
**project_id** | **str** | GCP project ID | 
**region** | **str** | GCP region | 

## Example

```python
from azentspublicclient.models.gcp_config import GcpConfig

# TODO update the JSON string below
json = "{}"
# create an instance of GcpConfig from a JSON string
gcp_config_instance = GcpConfig.from_json(json)
# print the JSON string representation of the object
print(GcpConfig.to_json())

# convert the object into a dict
gcp_config_dict = gcp_config_instance.to_dict()
# create an instance of GcpConfig from a dict
gcp_config_from_dict = GcpConfig.from_dict(gcp_config_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


