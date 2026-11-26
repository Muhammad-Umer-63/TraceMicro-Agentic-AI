package org.example;

/**
 * Types of relationships between classes
 */
public enum RelationshipType {
    EXTENDS,           // Class extends another class
    IMPLEMENTS,        // Class implements an interface
    CALLS,             // Class calls methods of another class
    USES,              // Class uses another class (field, parameter, return type)
    REFERENCES,        // Class references another class (local variable, etc.)
    INJECTS,           // Class injects another class (Spring, Java EE)
    ASSOCIATES,        // Class associates with another class (JPA, Hibernate)
    ANNOTATED_WITH,    // Class is annotated with another class
    CREATES,           // Class creates instances of another class
    PERSISTS,          // Class persists another class (Repository, DAO)
    DEPENDS_ON         // General dependency (Spring @DependsOn)
} 