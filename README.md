# natural-language-cli-infra
The infrastructure code used to manage the Natural Language to CLI commands project

## Infra

The infra is simple. Currently the only thing provisioned is 3 cloud storage buckets for dev purposes. These are used to house data in a `base`, `staging`, `mart` medallion structure.

## To do

- [ ] Improve this readme
- [ ] Add some team members with appropriate `iam` privalages
- [ ] Add a license (to be determined)
- [ ] We should be able to stay within the free tier always. i.e. 5gb storarage per month in Cloud Storage; then load and save the data into Google Collab for training (where we can use the free GPU or buy GPU credits). Therefore, a nice-to-have may be a cloud function to disable billing if we go beyond even something as small as €10. 


## Billing account
Ciaran currently owns the billing account under his personal email ciaranobrienmusic@gmail.com 
