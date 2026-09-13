# PrimaryModelReservation

Durable one-shot Session authority for a Primary candidate attempt.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**schema_version** | **int** |  | [optional] [default to 1]
**semantic_label** | **str** |  | 
**candidate** | [**ModelCandidateIdentity**](ModelCandidateIdentity.md) |  | 
**health_generation** | **int** |  | 
**reservation_generation** | **int** |  | 
**claim_token** | **str** |  | 
**created_at** | **datetime** |  | 
**expires_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.primary_model_reservation import PrimaryModelReservation

# TODO update the JSON string below
json = "{}"
# create an instance of PrimaryModelReservation from a JSON string
primary_model_reservation_instance = PrimaryModelReservation.from_json(json)
# print the JSON string representation of the object
print(PrimaryModelReservation.to_json())

# convert the object into a dict
primary_model_reservation_dict = primary_model_reservation_instance.to_dict()
# create an instance of PrimaryModelReservation from a dict
primary_model_reservation_from_dict = PrimaryModelReservation.from_dict(primary_model_reservation_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


