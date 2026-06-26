# AwsConfig

AWS Bedrock settings, stored as plaintext.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'aws_credentials']
**access_key_id** | **str** | AWS Access Key ID | 
**region** | **str** | AWS region | 
**role_arn** | **str** |  | [optional] 

## Example

```python
from azentspublicclient.models.aws_config import AwsConfig

# TODO update the JSON string below
json = "{}"
# create an instance of AwsConfig from a JSON string
aws_config_instance = AwsConfig.from_json(json)
# print the JSON string representation of the object
print(AwsConfig.to_json())

# convert the object into a dict
aws_config_dict = aws_config_instance.to_dict()
# create an instance of AwsConfig from a dict
aws_config_from_dict = AwsConfig.from_dict(aws_config_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


