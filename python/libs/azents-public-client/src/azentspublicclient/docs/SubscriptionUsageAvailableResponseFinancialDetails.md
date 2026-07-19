# SubscriptionUsageAvailableResponseFinancialDetails


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
**prepaid_balance_cents** | **int** |  | 
**payg_cap_cents** | **int** |  | 
**payg_used_cents** | **int** |  | 
**auto_top_up_enabled** | **bool** |  | 
**auto_top_up_amount_cents** | **int** |  | 
**auto_top_up_monthly_maximum_cents** | **int** |  | 
**credit_limit** | **float** |  | 
**credit_remaining** | **float** |  | 
**usage** | **float** |  | 
**usage_daily** | **float** |  | 
**usage_weekly** | **float** |  | 
**usage_monthly** | **float** |  | 
**limit_reset** | **str** |  | 
**include_byok_in_limit** | **bool** |  | 

## Example

```python
from azentspublicclient.models.subscription_usage_available_response_financial_details import SubscriptionUsageAvailableResponseFinancialDetails

# TODO update the JSON string below
json = "{}"
# create an instance of SubscriptionUsageAvailableResponseFinancialDetails from a JSON string
subscription_usage_available_response_financial_details_instance = SubscriptionUsageAvailableResponseFinancialDetails.from_json(json)
# print the JSON string representation of the object
print(SubscriptionUsageAvailableResponseFinancialDetails.to_json())

# convert the object into a dict
subscription_usage_available_response_financial_details_dict = subscription_usage_available_response_financial_details_instance.to_dict()
# create an instance of SubscriptionUsageAvailableResponseFinancialDetails from a dict
subscription_usage_available_response_financial_details_from_dict = SubscriptionUsageAvailableResponseFinancialDetails.from_dict(subscription_usage_available_response_financial_details_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


