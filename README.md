# In short...

UMM
Universal Model Modeler

a framework that can help fast, easy in the modern world gouverned by information


# Stucture of UMM

MADE FROM FOUR PARTS

Database that hold your model and data
- we choose a postgre database in docker

Server that uses the database to talk to clients
- this automatically performs the setup of the database schema to start using this

Clients that interact with the user
- this is used to use the tool to define what the user wants

Interfaces that read/write data to real-world devices
- small program to talk to the server to send/receive events/triggers to the modelled user's model.


# GOAL OF UMM

The goal of this application is to be able to model anything
while offering to the user an intuitive graphical experience that is fun and appreaciable.

modeling a process
modeling needs and requirements
modeling functional architure
modeling logical architecture
modeling physical architecture

examples could be the modeling of an entire facility
optimizing something specific

the application "Interfaces" can communicate with real-world data to update the state of the model (if numerical twin is wanted) or to behave as an intelligence framework that call other applications to performs automations.

