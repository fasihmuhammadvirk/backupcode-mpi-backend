# mpi-backend
Contains Code for MPI Backend

## Alembic
Almebic is used for migrations. To run migrations do the following

```bash
cd mpi_backend
export PYTHONPATH=../ 
alembic upgrade head
```

For this to run you need to have env variable set. We have included a sample .envrc file with this repo
rename it to `.envrc` and set the values correctly

For ease of use, using `direnv` is recommended.
You can follow instructions to install and use it here 
https://direnv.net