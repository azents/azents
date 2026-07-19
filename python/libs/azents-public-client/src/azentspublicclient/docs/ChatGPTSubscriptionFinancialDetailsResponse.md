# ChatGPTSubscriptionFinancialDetailsResponse

Management-only ChatGPT subscription financial details.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** |  |
**has_credits** | **bool** |  |
**unlimited** | **bool** |  |
**balance** | **str** |  |
**spend_limit** | **str** |  |
**spend_used** | **str** |  |
**spend_remaining_percent** | **float** |  |
**spend_resets_at** | **datetime** |  |
**reached_type** | **str** |  |

## Example

```python
from azentspublicclient.models.chat_gpt_subscription_financial_details_response import ChatGPTSubscriptionFinancialDetailsResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ChatGPTSubscriptionFinancialDetailsResponse from a JSON string
chat_gpt_subscription_financial_details_response_instance = ChatGPTSubscriptionFinancialDetailsResponse.from_json(json)
# print the JSON string representation of the object
print(ChatGPTSubscriptionFinancialDetailsResponse.to_json())

# convert the object into a dict
chat_gpt_subscription_financial_details_response_dict = chat_gpt_subscription_financial_details_response_instance.to_dict()
# create an instance of ChatGPTSubscriptionFinancialDetailsResponse from a dict
chat_gpt_subscription_financial_details_response_from_dict = ChatGPTSubscriptionFinancialDetailsResponse.from_dict(chat_gpt_subscription_financial_details_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
