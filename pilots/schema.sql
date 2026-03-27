CREATE TABLE Pilots(PilotID INTEGER PRIMARY KEY, UpdateTime TIMESTAMP, Status ENUM('Running', 'Waiting', 'Done', 'Failed'));;
CREATE TABLE PilotAttributes(PilotID INTEGER PRIMARY KEY, Cores USMALLINT, MemoryMB UINTEGER, FOREIGN KEY (PilotID) REFERENCES Pilots(PilotID));;

