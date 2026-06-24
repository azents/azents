# AwsSecrets

AWS IAM based secrets for AWS Bedrock.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  | [optional] [default to 'aws_credentials']
**secret_access_key** | **str** | AWS Secret Access Key |

## Example

```python
from azentspublicclient.models.aws_secrets import AwsSecrets

# TODO update the JSON string below
json = "{}"
# create an instance of AwsSecrets from a JSON string
aws_secrets_instance = AwsSecrets.from_json(json)
# print the JSON string representation of the object
print(AwsSecrets.to_json())

# convert the object into a dict
aws_secrets_dict = aws_secrets_instance.to_dict()
# create an instance of AwsSecrets from a dict
aws_secrets_from_dict = AwsSecrets.from_dict(aws_secrets_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
